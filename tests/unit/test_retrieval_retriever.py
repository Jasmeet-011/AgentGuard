"""Retriever composition with fake dense/sparse/rerank backends (no models, no network)."""

import pytest

from agentguard.config import Settings
from agentguard.models import Chunk, FirmInfo, RetrievedChunk, Trace
from agentguard.retrieval.retriever import (
    RetrievalMode,
    Retriever,
    StaleIndexError,
    interleave,
    merge_unique,
)

FIRMS = {
    "acme": FirmInfo(slug="acme", name="Acme", aliases=["acme"], doc_type="part2a"),
    "zeta": FirmInfo(slug="zeta", name="Zeta", aliases=["zeta"], doc_type="part2a"),
    "omni": FirmInfo(slug="omni", name="Omni", aliases=["omni"], doc_type="part2a"),
}


def make_chunk(doc_id: str, i: int) -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}-p1-{i}",
        firm_name=doc_id.title(),
        doc_id=doc_id,
        doc_type="part2a",
        adv_item=5,
        is_toc=False,
        item_title="Fees and Compensation",
        page_start=1,
        page_end=1,
        text=f"{doc_id} chunk {i}",
        token_count=4,
    )


CHUNKS = [make_chunk(doc, i) for doc in FIRMS for i in range(10)]


class FakeSearch:
    """Returns chunks in a fixed order (optionally per doc), filtered by doc_ids, top k."""

    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls: list[tuple[int, list[str] | None]] = []

    def search(self, query: str, k: int, doc_ids: list[str] | None) -> list[tuple[str, float]]:
        self.calls.append((k, doc_ids))
        hits = [cid for cid in self.order if doc_ids is None or cid.split("-")[0] in doc_ids]
        return [(cid, 1.0 / (rank + 1)) for rank, cid in enumerate(hits[:k])]


class FakeReranker:
    """Scores texts by a fixed preference map (unknown texts score 0)."""

    def __init__(self, prefs: dict[str, float] | None = None) -> None:
        self.prefs = prefs or {}
        self.calls = 0

    def score(self, query: str, texts: list[str]) -> list[float]:
        self.calls += 1
        return [self.prefs.get(t, 0.0) for t in texts]


def settings(**overrides: object) -> Settings:
    return Settings(anthropic_api_key="sk-test", **overrides)


def build(
    dense_order: list[str],
    sparse_order: list[str],
    reranker: FakeReranker | None = None,
    **overrides: object,
) -> tuple[Retriever, FakeSearch, FakeSearch, FakeReranker]:
    dense, sparse, rr = FakeSearch(dense_order), FakeSearch(sparse_order), reranker
    rr = rr or FakeReranker()
    retriever = Retriever(settings(**overrides), CHUNKS, FIRMS, dense, sparse, rr)
    return retriever, dense, sparse, rr


def ids(results: list[RetrievedChunk]) -> list[str]:
    return [r.chunk.chunk_id for r in results]


ALL_IDS = [c.chunk_id for c in CHUNKS]


def test_dense_mode_uses_only_dense() -> None:
    retriever, _, sparse, rr = build(ALL_IDS, list(reversed(ALL_IDS)))
    results = retriever.retrieve("what fees?", Trace(query_id="q"), mode="dense")
    assert ids(results) == ALL_IDS[:6]
    assert sparse.calls == [] and rr.calls == 0
    assert all(r.dense_score is not None and r.fused_score is None for r in results)
    assert all(r.rerank_score is None for r in results)


def test_hybrid_mode_fuses_without_rerank() -> None:
    dense_order = ["acme-p1-0", "acme-p1-1", "zeta-p1-0"]
    sparse_order = ["zeta-p1-0", "acme-p1-1", "omni-p1-0"]
    retriever, _, sparse, rr = build(dense_order, sparse_order)
    results = retriever.retrieve("what fees?", Trace(query_id="q"), mode="hybrid")
    # In both lists: zeta-p1-0 (ranks 3, 1) = 1/63 + 1/61 = 0.032266 edges out
    # acme-p1-1 (ranks 2, 2) = 2/62 = 0.032258.
    assert ids(results) == ["zeta-p1-0", "acme-p1-1", "acme-p1-0", "omni-p1-0"]
    assert rr.calls == 0 and len(sparse.calls) == 1
    assert all(r.fused_score is not None and r.rerank_score is None for r in results)


def test_hybrid_rerank_reorders_by_rerank_score() -> None:
    dense_order = ["acme-p1-0", "acme-p1-1", "zeta-p1-0"]
    sparse_order = ["zeta-p1-0", "acme-p1-1", "omni-p1-0"]
    reranker = FakeReranker({"omni chunk 0": 0.9, "acme chunk 0": 0.5})
    retriever, *_ = build(dense_order, sparse_order, reranker)
    results = retriever.retrieve("what fees?", Trace(query_id="q"), mode="hybrid_rerank")
    assert ids(results)[:2] == ["omni-p1-0", "acme-p1-0"]
    assert [r.rerank_score for r in results] == [0.9, 0.5, 0.0, 0.0]
    assert all(r.fused_score is not None for r in results)


def test_mode_defaults_to_settings() -> None:
    retriever, _, sparse, rr = build(ALL_IDS, ALL_IDS, retrieval_mode="dense")
    retriever.retrieve("fees", Trace(query_id="q"))
    assert sparse.calls == [] and rr.calls == 0


def test_returns_top_n_and_records_trace() -> None:
    retriever, *_ = build(ALL_IDS, ALL_IDS, rerank_top_n=4)
    trace = Trace(query_id="q")
    results = retriever.retrieve("fees", trace, mode="hybrid_rerank")
    assert len(results) == 4
    (event,) = trace.events
    assert event.node == "retrieve"
    assert event.detail["mode"] == "hybrid_rerank"
    assert event.detail["firm_filter"] is None
    assert event.detail["counts"] == {
        "dense_hits": 20,
        "sparse_hits": 20,
        "fused": 20,
        "reranked": 20,
    }
    assert set(event.detail["stage_ms"]) == {"dense", "sparse", "rerank"}
    assert event.detail["returned"] == 4


def test_single_firm_filters_both_backends() -> None:
    retriever, dense, sparse, _ = build(ALL_IDS, ALL_IDS)
    trace = Trace(query_id="q")
    results = retriever.retrieve("What fees does Zeta charge?", trace, mode="hybrid_rerank")
    assert {r.chunk.doc_id for r in results} == {"zeta"}
    assert dense.calls == [(20, ["zeta"])] and sparse.calls == [(20, ["zeta"])]
    assert trace.events[0].detail["firm_filter"] == ["zeta"]


def test_firm_match_is_word_boundary_not_substring() -> None:
    retriever, dense, _, _ = build(ALL_IDS, ALL_IDS)
    retriever.retrieve("acmeish omnivorous fees", Trace(query_id="q"), mode="dense")
    assert dense.calls == [(20, None)]


@pytest.mark.parametrize("mode", ["dense", "hybrid", "hybrid_rerank"])
def test_two_firms_split_results_evenly(mode: RetrievalMode) -> None:
    # Acme dominates every backend and the reranker; without the split it would take all 6.
    acme_first = [c for c in ALL_IDS if c.startswith("acme")] + [
        c for c in ALL_IDS if not c.startswith("acme")
    ]
    prefs = {f"acme chunk {i}": 0.9 - i * 0.01 for i in range(10)}
    prefs |= {f"zeta chunk {i}": 0.1 - i * 0.01 for i in range(10)}
    retriever, dense, sparse, _ = build(acme_first, acme_first, FakeReranker(prefs))
    trace = Trace(query_id="q")
    results = retriever.retrieve("Compare Acme and Zeta fees", trace, mode=mode)
    assert ids(results) == [
        "acme-p1-0",
        "zeta-p1-0",
        "acme-p1-1",
        "zeta-p1-1",
        "acme-p1-2",
        "zeta-p1-2",
    ]
    # Candidates are retrieved per firm, splitting the top_k budget.
    assert dense.calls == [(10, ["acme"]), (10, ["zeta"])]
    if mode != "dense":
        assert sparse.calls == [(10, ["acme"]), (10, ["zeta"])]
    detail = trace.events[0].detail
    assert detail["firm_filter"] == ["acme", "zeta"]
    assert detail["returned_per_firm"] == {"acme": 3, "zeta": 3}


def test_three_firms_two_each_ordered_by_first_mention() -> None:
    retriever, dense, _, _ = build(ALL_IDS, ALL_IDS)
    results = retriever.retrieve("omni vs zeta vs acme", Trace(query_id="q"), mode="dense")
    assert [r.chunk.doc_id for r in results] == ["omni", "zeta", "acme"] * 2
    assert dense.calls == [(7, ["omni"]), (7, ["zeta"]), (7, ["acme"])]


def test_interleave_fills_from_other_groups_when_one_runs_out() -> None:
    a = [RetrievedChunk(chunk=make_chunk("acme", i)) for i in range(1)]
    z = [RetrievedChunk(chunk=make_chunk("zeta", i)) for i in range(10)]
    assert ids(interleave([a, z], 6)) == [
        "acme-p1-0",
        "zeta-p1-0",
        "zeta-p1-1",
        "zeta-p1-2",
        "zeta-p1-3",
        "zeta-p1-4",
    ]
    assert interleave([[], []], 6) == []


def test_stale_index_fails_loudly() -> None:
    retriever, *_ = build(["ghost-p1-0"], [])
    with pytest.raises(StaleIndexError, match="rerun `agentguard ingest`"):
        retriever.retrieve("fees", Trace(query_id="q"), mode="dense")


def rc(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(chunk=next(c for c in CHUNKS if c.chunk_id == chunk_id))


def test_merge_unique_round_robins_and_skips_duplicates() -> None:
    a = [rc("acme-p1-0"), rc("acme-p1-1"), rc("acme-p1-2")]
    b = [rc("acme-p1-1"), rc("zeta-p1-0"), rc("zeta-p1-1")]
    assert ids(merge_unique([a, b], 4)) == ["acme-p1-0", "acme-p1-1", "zeta-p1-0", "acme-p1-2"]


def test_merge_unique_fills_from_the_longer_group_and_stops_at_n() -> None:
    a = [rc("acme-p1-0")]
    b = [rc("zeta-p1-0"), rc("zeta-p1-1"), rc("zeta-p1-2")]
    assert ids(merge_unique([a, b], 3)) == ["acme-p1-0", "zeta-p1-0", "zeta-p1-1"]
    assert ids(merge_unique([a, b], 10)) == ["acme-p1-0", "zeta-p1-0", "zeta-p1-1", "zeta-p1-2"]


def test_sub_queries_each_search_with_the_same_firm_filter_and_merge_to_top_n() -> None:
    retriever, dense, _, _ = build(ALL_IDS, ALL_IDS, rerank_top_n=4)
    results = retriever.retrieve(
        "acme fees and sec action",
        Trace(query_id="q"),
        mode="dense",
        sub_queries=["acme fees", "acme sec action"],
    )
    assert [doc for _, doc in dense.calls] == [["acme"], ["acme"]]  # both filtered to acme
    assert len(results) == 4 and len(set(ids(results))) == 4


def test_sub_queries_are_recorded_on_the_trace_only_when_there_are_several() -> None:
    retriever, _, _, _ = build(ALL_IDS, ALL_IDS)
    trace = Trace(query_id="q")
    retriever.retrieve("acme fees", trace, mode="dense", sub_queries=["acme fees"])
    retriever.retrieve("acme x y", trace, mode="dense", sub_queries=["acme x", "acme y"])
    assert "sub_queries" not in trace.events[0].detail
    assert trace.events[1].detail["sub_queries"] == ["acme x", "acme y"]
