"""Deterministic eval metrics on hand-made inputs."""

from datetime import UTC, datetime

import pytest

from agentguard.models import Answer, Chunk, CitedSentence, Trace, TraceEvent
from eval import metrics
from eval.golden import GoldenEntry
from eval.records import QuestionResult


def chunk(doc_id: str, item: int | None, doc_type: str = "part2a") -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}-{item}",
        firm_name=doc_id,
        doc_id=doc_id,
        doc_type=doc_type,  # type: ignore[arg-type]
        adv_item=item,
        is_toc=False,
        item_title=None,
        page_start=1,
        page_end=1,
        text="t",
        token_count=1,
    )


def golden(sources: list[tuple[str, int]], match: str = "any") -> GoldenEntry:
    return GoldenEntry.model_validate(
        {
            "id": "q",
            "split": "dev",
            "type": "answerable",
            "question": "?",
            "expected_sources": [
                {"firm": f, "doc_type": "part2a", "item": i, "page": 1} for f, i in sources
            ],
            "match": match,
            "key_facts": ["x"],
        }
    )


def test_source_hit_needs_firm_doc_type_and_item() -> None:
    entry = golden([("savvy", 5)])
    source = entry.expected_sources[0]
    assert metrics.source_hit(chunk("savvy", 5), source)
    assert not metrics.source_hit(chunk("savvy", 7), source)
    assert not metrics.source_hit(chunk("facet", 5), source)
    assert not metrics.source_hit(chunk("savvy", 5, "wrap_appendix1"), source)
    assert not metrics.source_hit(chunk("savvy", None), source)


def test_match_any_needs_one_source() -> None:
    entry = golden([("savvy", 5), ("savvy", 7)])
    assert metrics.retrieval_hit([chunk("savvy", 7)], entry)
    assert not metrics.retrieval_hit([chunk("savvy", 9)], entry)


def test_match_all_needs_every_source() -> None:
    entry = golden([("savvy", 5), ("savvy", 7)], match="all")
    assert not metrics.retrieval_hit([chunk("savvy", 5)], entry)
    assert metrics.retrieval_hit([chunk("savvy", 5), chunk("savvy", 7)], entry)


def test_comparison_needs_a_chunk_from_every_expected_firm() -> None:
    entry = golden([("savvy", 5), ("facet", 5)])
    assert not metrics.retrieval_hit([chunk("savvy", 5), chunk("savvy", 7)], entry)
    assert metrics.retrieval_hit([chunk("savvy", 5), chunk("facet", 9)], entry)


def test_empty_retrieval_is_a_miss() -> None:
    assert not metrics.retrieval_hit([], golden([("savvy", 5)]))


def test_key_fact_score_is_the_fraction_present() -> None:
    assert metrics.key_fact_score([True, False, True, True]) == 0.75
    with pytest.raises(ValueError):
        metrics.key_fact_score([])


def test_faithfulness_counts_only_fully_supported() -> None:
    assert metrics.faithfulness_score(["supported", "partial", "unsupported", "supported"]) == 0.5
    assert metrics.faithfulness_score([]) is None


def test_rate_mean_and_percentile_handle_empty_input() -> None:
    assert metrics.rate([]) is None
    assert metrics.mean([]) is None
    assert metrics.percentile([], 50) is None
    assert metrics.rate([True, False, False, False]) == 0.25


def test_percentile_interpolates() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert metrics.percentile(values, 50) == 25.0
    assert metrics.percentile(values, 0) == 10.0
    assert metrics.percentile(values, 100) == 40.0
    assert metrics.percentile([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        metrics.percentile(values, 101)


def event(node: str, **kwargs: object) -> TraceEvent:
    detail = kwargs.pop("detail", {})
    return TraceEvent(node=node, started_at=datetime.now(UTC), detail=detail, **kwargs)  # type: ignore[arg-type]


def test_latency_and_cost_use_original_values_on_cache_hits() -> None:
    trace = Trace(query_id="t")
    trace.events = [
        event("retrieve", duration_ms=100.0),
        event(
            "generate",
            duration_ms=2.0,
            cost_usd=0.0,
            detail={
                "cached": True,
                "original_duration_ms": 3000.0,
                "original_cost_usd": 0.01,
            },
        ),
        event("finalize", duration_ms=1.0, cost_usd=0.002),
    ]
    assert metrics.latency_and_cost(trace) == (3101.0, pytest.approx(0.012))


def answer(sentences: list[CitedSentence]) -> Answer:
    return Answer(
        question="?",
        sentences=sentences,
        refused=not sentences,
        refusal_reason=None,
        refusal_message=None,
        retrieved=[],
        verification=[],
        removed_sentences=[],
    )


def test_invalid_citation_counts_add_dropped_to_kept() -> None:
    trace = Trace(query_id="t")
    trace.events = [event("generate", detail={"invalid_citations_dropped": 2})]
    sentences = [CitedSentence(text="a", citations=["c1", "c2"])]
    assert metrics.invalid_citation_counts(answer(sentences), trace) == (2, 4)


def test_invalid_citation_counts_when_nothing_was_dropped_or_cited() -> None:
    trace = Trace(query_id="t")
    trace.events = [event("generate")]
    assert metrics.invalid_citation_counts(answer([]), trace) == (0, 0)


def row(kind: str, **kwargs: object) -> QuestionResult:
    base = {
        "id": "x",
        "type": kind,
        "question": "?",
        "refused": False,
        "refusal_reason": None,
        "answer_text": "",
        "retrieved_chunk_ids": [],
    }
    return QuestionResult.model_validate(base | kwargs)


def test_aggregate_computes_each_rate_over_its_own_question_type() -> None:
    rows = [
        row("answerable", retrieval_hit=True, correctness=1.0, faithfulness=1.0, latency_ms=10),
        row("answerable", retrieval_hit=False, correctness=0.5, refused=True, latency_ms=30),
        row("unanswerable", refused=True, latency_ms=20),
        row("unanswerable", refused=False, invalid_citations=1, total_citations=4),
        row("policy", refused=True, refusal_reason="policy"),
        row("policy", refused=True, refusal_reason="insufficient_evidence"),
    ]
    agg = metrics.aggregate(rows)
    assert (agg.n_answerable, agg.n_unanswerable, agg.n_policy) == (2, 2, 2)
    assert agg.retrieval_recall == 0.5
    assert agg.correctness == 0.75
    assert agg.faithfulness == 1.0  # only rows that have a faithfulness score
    assert agg.false_refusal_rate == 0.5
    assert agg.correct_refusal_rate == 0.5
    assert agg.policy_block_rate == 1.0
    assert agg.policy_reason_rate == 0.5
    assert agg.invalid_citation_rate == 0.25


def test_aggregate_of_all_refused_answerables_has_no_faithfulness() -> None:
    rows = [row("answerable", retrieval_hit=False, correctness=0.0, refused=True)]
    agg = metrics.aggregate(rows)
    assert agg.faithfulness is None
    assert agg.false_refusal_rate == 1.0
    assert agg.invalid_citation_rate is None


def test_aggregate_of_no_rows_is_all_none() -> None:
    agg = metrics.aggregate([])
    assert agg.retrieval_recall is None
    assert agg.latency_p50_ms is None
    assert agg.cost_per_query_usd is None
