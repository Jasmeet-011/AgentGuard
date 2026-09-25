from datetime import UTC, datetime

from agentguard.models import (
    Answer,
    Chunk,
    CitedSentence,
    RetrievedChunk,
    Trace,
    TraceEvent,
    VerificationResult,
)
from agentguard.ui import (
    DEMO_QUESTIONS,
    demo_label,
    policy_category,
    removed_with_reasons,
    render_answer,
    strip_header,
    sub_queries,
    trace_rows,
)


def chunk(cid: str, start: int = 3, end: int = 3) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            chunk_id=cid,
            firm_name="Savvy",
            doc_id="savvy",
            doc_type="part2a",
            adv_item=5,
            is_toc=False,
            item_title="Fees",
            page_start=start,
            page_end=end,
            text="text",
            token_count=1,
        )
    )


def event(node: str, **detail: object) -> TraceEvent:
    return TraceEvent(node=node, started_at=datetime.now(UTC), duration_ms=1.0, detail=detail)


def answer(**kw: object) -> Answer:
    base = {
        "question": "q",
        "sentences": [],
        "refused": False,
        "refusal_reason": None,
        "refusal_message": None,
        "retrieved": [chunk("a"), chunk("b", 4, 5)],
        "verification": [],
        "removed_sentences": [],
    }
    return Answer(**(base | kw))


def test_demo_questions_are_the_seven_specified() -> None:
    assert len(DEMO_QUESTIONS) == 7
    assert DEMO_QUESTIONS[0] == "What is Savvy's minimum account size?"
    assert "decomposition demo" in demo_label(2)
    assert demo_label(0) == "Due diligence · 1. What is Savvy's minimum account size?"


def test_citations_numbered_by_first_use_and_shared() -> None:
    a = answer(
        sentences=[
            CitedSentence(text="s1", citations=["b"]),
            CitedSentence(text="s2", citations=["a", "b"]),
        ]
    )
    r = render_answer(a)
    assert [s.numbers for s in r.sentences] == [[1], [2, 1]]
    assert [(c.number, c.chunk.chunk_id) for c in r.citations] == [(1, "b"), (2, "a")]
    assert r.citations[0].pages == "pages 4-5"
    assert r.citations[1].label == "Savvy | Item 5 | page 3"


def test_partial_marked_and_removed_reported() -> None:
    a = answer(
        sentences=[CitedSentence(text="keep", citations=["a"])],
        removed_sentences=[CitedSentence(text="bad", citations=["a"])],
        verification=[
            VerificationResult(sentence_index=1, verdict="partial", reason="r1"),
            VerificationResult(sentence_index=2, verdict="unsupported", reason="fabricated"),
        ],
    )
    assert render_answer(a).sentences[0].partial
    assert removed_with_reasons(a) == [("bad", "fabricated")]


def test_sub_queries_only_when_split() -> None:
    split = Trace(query_id="x", events=[event("decompose", sub_queries=["a", "b"])])
    single = Trace(query_id="x", events=[event("decompose", sub_queries=["a"])])
    assert sub_queries(split) == ["a", "b"]
    assert sub_queries(single) == []
    assert sub_queries(Trace(query_id="x")) == []


def test_policy_category() -> None:
    t = Trace(query_id="x", events=[event("policy_guard", category="pii_request")])
    assert policy_category(t) == "pii_request"
    assert policy_category(Trace(query_id="x")) is None


def test_trace_rows_show_original_values_for_cached_events() -> None:
    cached = event(
        "generate",
        cached=True,
        original_duration_ms=900.0,
        original_input_tokens=10,
        original_output_tokens=5,
        original_cost_usd=0.01,
    )
    rows = trace_rows(Trace(query_id="x", events=[cached, event("retrieve")]))
    assert (rows[0].ms, rows[0].input_tokens, rows[0].cost_usd) == (900.0, 10, 0.01)
    assert rows[0].cached is True
    assert rows[1].cached is False


def test_strip_header_removes_only_the_retrieval_header_line() -> None:
    c = chunk("a").chunk
    with_header = c.model_copy(update={"text": "Savvy | Item 5: Fees\nbody | pipe\nmore"})
    assert strip_header(with_header) == "body | pipe\nmore"
    assert with_header.text.startswith("Savvy | Item 5")  # stored chunk untouched
    other = c.model_copy(update={"text": "No header here\nbody"})
    assert strip_header(other) == "No header here\nbody"


def test_demo_groups_follow_use_case() -> None:
    groups = [demo_label(i).split(" · ")[0] for i in range(7)]
    assert groups == ["Due diligence"] * 4 + ["Honest refusal"] + ["Guardrails"] * 2
