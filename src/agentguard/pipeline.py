"""Shared, load-once model resources, and a cheap `Pipeline` built from them.

`Resources` holds everything expensive to load (embedding model, Qdrant client, BM25
index, reranker model, firms registry, LLM client). `Pipeline` wraps a `Resources`
plus a `Settings` into a runnable graph without loading anything itself, so an eval
harness or a UI can build one `Resources` and cheaply construct many `Pipeline`
variants (different retrieval mode, thresholds, flags, model *names*) from it.
"""

import uuid
from dataclasses import dataclass

from qdrant_client import QdrantClient

from agentguard.agents.decomposer import Decomposer
from agentguard.agents.generator import Generator
from agentguard.agents.verifier import Verifier
from agentguard.config import Settings
from agentguard.graph import PipelineState, build_graph
from agentguard.ingest.firms import load_firms
from agentguard.ingest.pipeline import load_chunks
from agentguard.llm import LLMClient
from agentguard.models import Answer, FirmInfo, Trace
from agentguard.retrieval.dense import DenseSearcher, Embedder, open_qdrant
from agentguard.retrieval.rerank import Reranker
from agentguard.retrieval.retriever import Retriever
from agentguard.retrieval.sparse import SparseSearcher

# Settings fields that with_overrides may change without reloading anything in Resources:
# they only affect per-call behavior of components already built from Resources. Anything
# else changes what a model/client/index was loaded with or from, so it is refused.
ALLOWED_OVERRIDE_FIELDS: frozenset[str] = frozenset(
    {
        "retrieval_mode",
        "dense_top_k",
        "sparse_top_k",
        "rrf_k",
        "rerank_top_n",
        "enable_policy_guard",
        "enable_verifier",
        "enable_score_threshold",
        "enable_decomposition",
        "min_rerank_score",
        "verifier_max_drop_ratio",
        "generator_model",
        "verifier_model",
        "judge_model",
        "policy_model",
    }
)


@dataclass(frozen=True)
class Resources:
    """The heavy, load-once objects. `Resources.load` is the only place models are loaded."""

    embedder: Embedder
    qdrant_client: QdrantClient
    bm25: SparseSearcher
    reranker: Reranker
    firms: dict[str, FirmInfo]
    llm: LLMClient

    @classmethod
    def load(cls, settings: Settings) -> "Resources":
        """Load the embedding model, Qdrant client, BM25 index, reranker, firms, and LLM client."""
        return cls(
            embedder=Embedder(settings.embedding_model, settings.embedding_query_prefix),
            qdrant_client=open_qdrant(settings.qdrant_path),
            bm25=SparseSearcher(settings.processed_dir),
            reranker=Reranker(settings.reranker_model),
            firms=load_firms(settings.raw_dir),
            llm=LLMClient(settings),
        )


class Pipeline:
    """A `Retriever` + `Generator` + compiled graph for one `Settings`, over shared `Resources`.

    Construction only wraps already-loaded resources (plus chunks.jsonl, cheap to reread); it
    never loads a model, index, or client.
    """

    def __init__(self, settings: Settings, resources: Resources) -> None:
        self._settings = settings
        self._resources = resources
        chunks = load_chunks(settings.processed_dir)
        dense = DenseSearcher(resources.qdrant_client, resources.embedder)
        retriever = Retriever(
            settings, chunks, resources.firms, dense, resources.bm25, resources.reranker
        )
        generator = Generator(settings, resources.llm)
        verifier = Verifier(settings, resources.llm)
        decomposer = Decomposer(settings, resources.llm)
        self._graph = build_graph(settings, retriever, generator, verifier, decomposer)

    @property
    def resources(self) -> Resources:
        """The shared `Resources` this pipeline was built from (e.g. for the eval judge's LLM)."""
        return self._resources

    @classmethod
    def from_settings(cls, settings: Settings) -> "Pipeline":
        """Load a fresh `Resources` for `settings`, then build a `Pipeline` from it."""
        return cls(settings, Resources.load(settings))

    def run(self, question: str) -> tuple[Answer, Trace]:
        """Answer `question` once through the compiled graph."""
        trace = Trace(query_id=uuid.uuid4().hex)
        initial: PipelineState = {
            "question": question,
            "trace": trace,
            "sub_queries": [],
            "retrieved": [],
            "generator_output": None,
            "verification": [],
            "removed_sentences": [],
            "verifier_rejected": False,
            "answer": None,
        }
        result = self._graph.invoke(initial)
        answer = result["answer"]
        assert answer is not None  # finalize_node always sets it
        return answer, trace

    def with_overrides(self, **updates: object) -> "Pipeline":
        """A new `Pipeline` for `settings.model_copy(update=updates)`, sharing these `Resources`.

        Only fields in `ALLOWED_OVERRIDE_FIELDS` may be changed this way. Anything else would
        require reloading a model, index, or client, so it raises `ValueError` naming the field
        instead of silently reloading (or silently not applying it).
        """
        for field in updates:
            if field not in ALLOWED_OVERRIDE_FIELDS:
                raise ValueError(
                    f"{field!r} cannot be changed via with_overrides: it requires reloading "
                    "Resources. Build a new Pipeline with Pipeline.from_settings instead."
                )
        return Pipeline(self._settings.model_copy(update=updates), self._resources)


def run_pipeline(question: str, settings: Settings) -> tuple[Answer, Trace]:
    """Load resources fresh and answer one question.

    For more than one question, build a `Pipeline` (or `Resources`) once and reuse it instead:
    this loads every model, index, and client from scratch on every call.
    """
    return Pipeline.from_settings(settings).run(question)
