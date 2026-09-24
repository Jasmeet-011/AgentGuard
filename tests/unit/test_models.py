from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentguard.models import (
    Answer,
    Chunk,
    CitedSentence,
    GeneratorOutput,
    PolicyDecision,
    RetrievedChunk,
    Trace,
    TraceEvent,
    VerificationResult,
)


def make_chunk() -> Chunk:
    return Chunk(
        chunk_id="acme-p7-0",
        firm_name="Acme Advisors",
        doc_id="acme",
        doc_type="part2a",
        adv_item=5,
        is_toc=False,
        item_title="Fees and Compensation",
        page_start=7,
        page_end=8,
        text="Acme Advisors | Item 5: Fees and Compensation\nWe charge 1.25% annually.",
        token_count=12,
    )


def make_answer() -> Answer:
    sentence = CitedSentence(text="Acme charges 1.25% annually.", citations=["acme-p7-0"])
    return Answer(
        question="What does Acme charge?",
        sentences=[sentence],
        refused=False,
        refusal_reason=None,
        refusal_message=None,
        retrieved=[RetrievedChunk(chunk=make_chunk(), fused_score=0.03, rerank_score=4.2)],
        verification=[VerificationResult(sentence_index=0, verdict="supported", reason="ok")],
        removed_sentences=[],
    )


def test_answer_round_trips_through_json() -> None:
    answer = make_answer()
    assert Answer.model_validate_json(answer.model_dump_json()) == answer


def test_retrieved_chunk_scores_default_to_none() -> None:
    retrieved = RetrievedChunk(chunk=make_chunk())
    assert retrieved.dense_score is None
    assert retrieved.rerank_score is None


def test_literals_reject_unknown_values() -> None:
    with pytest.raises(ValidationError):
        PolicyDecision(category="financial_advice", reason="x")
    with pytest.raises(ValidationError):
        VerificationResult(sentence_index=0, verdict="maybe", reason="x")
    with pytest.raises(ValidationError):
        make_answer().model_validate({**make_answer().model_dump(), "refusal_reason": "bored"})


def test_trace_computed_totals_and_round_trip() -> None:
    now = datetime.now(UTC)
    trace = Trace(
        query_id="q1",
        events=[
            TraceEvent(
                node="a",
                started_at=now,
                duration_ms=10,
                input_tokens=100,
                output_tokens=20,
                cost_usd=0.01,
            ),
            TraceEvent(node="b", started_at=now, duration_ms=5.5, detail={"cached": True}),
        ],
    )
    assert trace.total_ms == 15.5
    assert trace.total_tokens == 120
    assert trace.total_cost_usd == pytest.approx(0.01)
    dumped = trace.model_dump(mode="json")
    assert dumped["total_tokens"] == 120
    assert Trace.model_validate(dumped) == trace


def test_empty_trace_totals_are_zero() -> None:
    trace = Trace(query_id="q2")
    assert (trace.total_ms, trace.total_tokens, trace.total_cost_usd) == (0, 0, 0)


def test_cited_sentence_requires_at_least_one_citation() -> None:
    with pytest.raises(ValidationError, match="citations"):
        CitedSentence(text="Acme charges 1.25%.", citations=[])


def test_generator_output_defaults_to_no_sentences_and_no_partial_note() -> None:
    output = GeneratorOutput(refused=True, refusal_message="Not in the documents.")
    assert output.sentences == []
    assert output.partial_note is None


def test_generator_output_schema_marks_citations_min_items() -> None:
    schema = GeneratorOutput.model_json_schema()
    citations_schema = schema["$defs"]["CitedSentence"]["properties"]["citations"]
    assert citations_schema["minItems"] == 1


def test_answer_partial_note_defaults_to_none() -> None:
    assert make_answer().partial_note is None
