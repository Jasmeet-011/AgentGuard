import pytest

from agentguard.retrieval.fusion import rrf_fuse


def test_rrf_scores_match_formula() -> None:
    fused = dict(rrf_fuse([["a", "b"], ["b", "c"]], rrf_k=60))
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest.approx(1 / 62)


def test_rrf_orders_by_fused_score() -> None:
    dense = ["a", "b", "c", "d"]
    sparse = ["c", "a", "e"]
    order = [cid for cid, _ in rrf_fuse([dense, sparse], rrf_k=60)]
    # a: 1/61 + 1/62, c: 1/63 + 1/61, b: 1/62, e: 1/63, d: 1/64
    assert order == ["a", "c", "b", "e", "d"]


def test_item_in_both_lists_beats_top_of_one_list() -> None:
    order = [cid for cid, _ in rrf_fuse([["x", "both"], ["y", "both"]], rrf_k=1)]
    # both: 1/3 + 1/3 = 0.667 beats x, y: 1/2 each.
    assert order[0] == "both"


def test_ties_broken_by_best_rank_then_chunk_id() -> None:
    # b and z each appear once at rank 1 -> exact tie, broken by chunk_id.
    # a and y tie on score (rank 2 in one list); also broken by chunk_id.
    order = [cid for cid, _ in rrf_fuse([["z", "y"], ["b", "a"]], rrf_k=60)]
    assert order == ["b", "z", "a", "y"]


def test_tie_break_prefers_better_best_rank() -> None:
    # k=2: "zp" has ranks (1, 4) -> 1/3 + 1/6 = 0.5; "aq" has ranks (2, 2) -> 1/4 + 1/4 = 0.5.
    # The scores tie exactly; "zp" wins on its better best rank even though "aq" sorts first.
    lists = [["zp", "aq", "f1", "f2"], ["f3", "aq", "f4", "zp"]]
    fused = rrf_fuse(lists, rrf_k=2)
    scores = dict(fused)
    assert scores["zp"] == scores["aq"]
    order = [cid for cid, _ in fused]
    assert order.index("zp") < order.index("aq")


def test_rrf_is_independent_of_list_order() -> None:
    lists = [["a", "b", "c"], ["c", "d"], ["d", "a", "e"]]
    assert rrf_fuse(lists, rrf_k=60) == rrf_fuse(list(reversed(lists)), rrf_k=60)


def test_rrf_empty_inputs() -> None:
    assert rrf_fuse([], rrf_k=60) == []
    assert rrf_fuse([[], []], rrf_k=60) == []
    assert rrf_fuse([["a"], []], rrf_k=60) == [("a", pytest.approx(1 / 61))]


def test_rrf_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="rrf_k must be positive"):
        rrf_fuse([["a"]], rrf_k=0)
    with pytest.raises(ValueError, match="duplicate"):
        rrf_fuse([["a", "a"]], rrf_k=60)
