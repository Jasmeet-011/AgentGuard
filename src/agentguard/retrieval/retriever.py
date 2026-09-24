"""Compose dense, sparse, fusion, and rerank according to `retrieval_mode`."""

import logging
import math
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Literal, Protocol, TypeVar

from agentguard.config import Settings
from agentguard.ingest.firms import load_firms, match_firms
from agentguard.ingest.pipeline import load_chunks
from agentguard.models import Chunk, FirmInfo, RetrievedChunk, Trace
from agentguard.retrieval.dense import DenseSearcher, Embedder, open_qdrant
from agentguard.retrieval.fusion import rrf_fuse
from agentguard.retrieval.rerank import Reranker, RerankScorer, rerank
from agentguard.retrieval.sparse import SparseSearcher
from agentguard.trace import trace_node

logger = logging.getLogger(__name__)

RetrievalMode = Literal["dense", "hybrid", "hybrid_rerank"]
T = TypeVar("T")


class StaleIndexError(Exception):
    """An index returned a chunk_id that chunks.jsonl does not contain."""


class SearchBackend(Protocol):
    """Dense or sparse search: top `k` (chunk_id, score), optionally limited to `doc_ids`."""

    def search(self, query: str, k: int, doc_ids: list[str] | None) -> list[tuple[str, float]]: ...


class LazyReranker:
    """Loads the cross-encoder on first use, so dense/hybrid runs never pay for it."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._reranker: Reranker | None = None

    def score(self, query: str, texts: list[str]) -> list[float]:
        if self._reranker is None:
            self._reranker = Reranker(self._model_name)
        return self._reranker.score(query, texts)


def interleave(groups: list[list[RetrievedChunk]], n: int) -> list[RetrievedChunk]:
    """Take up to `n` chunks round-robin across ranked groups (best of each group first).

    With two firms and n=6 this gives 3 + 3, so one firm cannot crowd out the other. If a
    group runs out, the remaining slots go to the other groups.
    """
    selected: list[RetrievedChunk] = []
    depth = 0
    while len(selected) < n and any(depth < len(g) for g in groups):
        selected.extend(g[depth] for g in groups if depth < len(g))
        depth += 1
    return selected[:n]


class Retriever:
    """Hybrid retriever over the indexed ADV chunks, with a firm filter from the query."""

    def __init__(
        self,
        settings: Settings,
        chunks: list[Chunk],
        firms: dict[str, FirmInfo],
        dense: SearchBackend,
        sparse: SearchBackend,
        reranker: RerankScorer,
    ) -> None:
        self._settings = settings
        self._chunks = {c.chunk_id: c for c in chunks}
        self._firms = firms
        self._dense = dense
        self._sparse = sparse
        self._reranker = reranker

    @classmethod
    def from_settings(cls, settings: Settings) -> "Retriever":
        """Load chunks, firms, both indexes, and the embedder. The reranker loads lazily."""
        embedder = Embedder(settings.embedding_model, settings.embedding_query_prefix)
        return cls(
            settings,
            chunks=load_chunks(settings.processed_dir),
            firms=load_firms(settings.raw_dir),
            dense=DenseSearcher(open_qdrant(settings.qdrant_path), embedder),
            sparse=SparseSearcher(settings.processed_dir),
            reranker=LazyReranker(settings.reranker_model),
        )

    def retrieve(
        self, query: str, trace: Trace, mode: RetrievalMode | None = None
    ) -> list[RetrievedChunk]:
        """Top `rerank_top_n` chunks for `query` (mode defaults to `settings.retrieval_mode`).

        If the query names firms, results are filtered to them. With 2+ firms, candidates are
        retrieved per firm and the final slots are split evenly across firms.
        """
        mode = mode or self._settings.retrieval_mode
        with trace_node(trace, "retrieve") as event:
            firm_slugs = match_firms(query, self._firms)
            # One group per named firm; a single group over the whole corpus if none is named.
            groups: list[list[str] | None] = [[s] for s in firm_slugs] or [None]
            stats = _Stats()
            ranked = [self._rank_group(query, mode, g, len(groups), stats) for g in groups]
            results = interleave(ranked, self._settings.rerank_top_n)
            event.detail = {
                "mode": mode,
                "firm_filter": firm_slugs or None,
                "counts": dict(stats.counts),
                "stage_ms": {k: round(v, 1) for k, v in stats.stage_ms.items()},
                "returned": len(results),
                "returned_per_firm": dict(Counter(r.chunk.doc_id for r in results)),
            }
            logger.debug("retrieve %r -> %s", query, event.detail)
        return results

    def _rank_group(
        self,
        query: str,
        mode: RetrievalMode,
        doc_ids: list[str] | None,
        n_groups: int,
        stats: "_Stats",
    ) -> list[RetrievedChunk]:
        """Ranked candidates for one firm group (or the whole corpus if `doc_ids` is None)."""
        dense_k = math.ceil(self._settings.dense_top_k / n_groups)
        dense_hits = self._timed(
            stats, "dense", lambda: self._dense.search(query, dense_k, doc_ids)
        )
        stats.counts["dense_hits"] += len(dense_hits)
        if mode == "dense":
            return [self._retrieved(cid, dense_score=s) for cid, s in dense_hits]
        sparse_k = math.ceil(self._settings.sparse_top_k / n_groups)
        sparse_hits = self._timed(
            stats, "sparse", lambda: self._sparse.search(query, sparse_k, doc_ids)
        )
        stats.counts["sparse_hits"] += len(sparse_hits)
        fused = self._fuse(dense_hits, sparse_hits)
        stats.counts["fused"] += len(fused)
        if mode == "hybrid":
            return fused
        stats.counts["reranked"] += len(fused)
        return self._timed(stats, "rerank", lambda: rerank(self._reranker, query, fused))

    def _fuse(
        self, dense_hits: list[tuple[str, float]], sparse_hits: list[tuple[str, float]]
    ) -> list[RetrievedChunk]:
        dense_scores, sparse_scores = dict(dense_hits), dict(sparse_hits)
        rankings = [[cid for cid, _ in dense_hits], [cid for cid, _ in sparse_hits]]
        return [
            self._retrieved(
                cid,
                dense_score=dense_scores.get(cid),
                sparse_score=sparse_scores.get(cid),
                fused_score=score,
            )
            for cid, score in rrf_fuse(rankings, self._settings.rrf_k)
        ]

    def _retrieved(self, chunk_id: str, **scores: float | None) -> RetrievedChunk:
        chunk = self._chunks.get(chunk_id)
        if chunk is None:
            raise StaleIndexError(
                f"Index returned {chunk_id!r}, which is not in chunks.jsonl. "
                "The indexes are stale: rerun `agentguard ingest`."
            )
        return RetrievedChunk(chunk=chunk, **scores)

    @staticmethod
    def _timed(stats: "_Stats", stage: str, fn: Callable[[], T]) -> T:
        start = time.perf_counter()
        result = fn()
        stats.stage_ms[stage] += (time.perf_counter() - start) * 1000
        return result


class _Stats:
    """Per-stage candidate counts and wall time for one `retrieve` call (summed over groups)."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.stage_ms: defaultdict[str, float] = defaultdict(float)
