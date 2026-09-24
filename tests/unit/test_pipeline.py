"""Resources are loaded once and shared; with_overrides never reloads them."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from agentguard.config import Settings
from agentguard.models import Answer
from agentguard.pipeline import ALLOWED_OVERRIDE_FIELDS, Pipeline

LOADER_NAMES = ("embedder", "open_qdrant", "bm25", "reranker", "firms", "llm")


def settings(**overrides: object) -> Settings:
    return Settings(anthropic_api_key="sk-test", **overrides)


def fake_answer(question: str) -> Answer:
    return Answer(
        question=question,
        sentences=[],
        refused=True,
        refusal_reason="insufficient_evidence",
        refusal_message="stub",
        partial_note=None,
        retrieved=[],
        verification=[],
        removed_sentences=[],
    )


@pytest.fixture
def loaders() -> Iterator[dict[str, MagicMock]]:
    """Patch every constructor `Resources.load` calls, and stub the compiled graph's run."""
    with (
        patch("agentguard.pipeline.Embedder") as embedder,
        patch("agentguard.pipeline.open_qdrant") as open_qdrant,
        patch("agentguard.pipeline.SparseSearcher") as bm25,
        patch("agentguard.pipeline.Reranker") as reranker,
        patch("agentguard.pipeline.load_firms") as firms,
        patch("agentguard.pipeline.LLMClient") as llm,
        patch("agentguard.pipeline.load_chunks", return_value=[]),
        patch("agentguard.pipeline.DenseSearcher"),
        patch("agentguard.pipeline.Retriever"),
        patch("agentguard.pipeline.Generator"),
        patch("agentguard.pipeline.build_graph") as build_graph,
    ):
        graph = MagicMock()
        graph.invoke.side_effect = lambda state: {"answer": fake_answer(state["question"])}
        build_graph.return_value = graph
        yield {
            "embedder": embedder,
            "open_qdrant": open_qdrant,
            "bm25": bm25,
            "reranker": reranker,
            "firms": firms,
            "llm": llm,
            "graph": graph,
        }


def test_two_runs_plus_a_with_overrides_run_load_each_resource_once(
    loaders: dict[str, MagicMock],
) -> None:
    pipeline = Pipeline.from_settings(settings())
    pipeline.run("What fees does Acme charge?")
    pipeline.run("Does Acme have custody?")

    dense_pipeline = pipeline.with_overrides(retrieval_mode="dense")
    dense_pipeline.run("What fees does Fisher charge?")

    for name in LOADER_NAMES:
        assert loaders[name].call_count == 1, f"{name} loaded {loaders[name].call_count} times"
    assert loaders["graph"].invoke.call_count == 3


def test_with_overrides_shares_the_same_resources_instance(loaders: dict[str, MagicMock]) -> None:
    pipeline = Pipeline.from_settings(settings())
    dense_pipeline = pipeline.with_overrides(retrieval_mode="dense")
    assert dense_pipeline._resources is pipeline._resources
    assert dense_pipeline._settings.retrieval_mode == "dense"
    assert pipeline._settings.retrieval_mode != "dense"


def test_with_overrides_applies_allowed_field(loaders: dict[str, MagicMock]) -> None:
    pipeline = Pipeline.from_settings(settings())
    overridden = pipeline.with_overrides(generator_model="claude-haiku-4-5-20251001")
    assert overridden._settings.generator_model == "claude-haiku-4-5-20251001"


@pytest.mark.parametrize(
    "field",
    ["embedding_model", "reranker_model", "raw_dir", "anthropic_api_key", "enable_llm_cache"],
)
def test_with_overrides_rejects_resource_level_fields(
    loaders: dict[str, MagicMock], field: str
) -> None:
    pipeline = Pipeline.from_settings(settings())
    with pytest.raises(ValueError, match=field):
        pipeline.with_overrides(**{field: "x"})
    # Rejecting an override must not have loaded anything a second time.
    for name in LOADER_NAMES:
        assert loaders[name].call_count == 1


def test_allowed_override_fields_matches_the_spec(loaders: dict[str, MagicMock]) -> None:
    assert ALLOWED_OVERRIDE_FIELDS == {
        "retrieval_mode",
        "dense_top_k",
        "sparse_top_k",
        "rrf_k",
        "rerank_top_n",
        "enable_policy_guard",
        "enable_verifier",
        "enable_score_threshold",
        "min_rerank_score",
        "verifier_max_drop_ratio",
        "generator_model",
        "verifier_model",
        "judge_model",
        "policy_model",
    }
