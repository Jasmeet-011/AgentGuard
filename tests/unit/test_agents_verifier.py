"""Verifier logic with a fake LLM client (no network)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from agentguard.agents.verifier import (
    Verifier,
    VerifierError,
    VerifierOutput,
    apply_verdicts,
    build_user_message,
)
from agentguard.config import Settings
from agentguard.models import (
    Chunk,
    CitedSentence,
    RetrievedChunk,
    Trace,
    TraceEvent,
    VerificationResult,
)


def sentence(text: str, *citations: str) -> CitedSentence:
    return CitedSentence(text=text, citations=list(citations or ["c1"]))


def result(index: int, verdict: str) -> VerificationResult:
    return VerificationResult(sentence_index=index, verdict=verdict, reason=f"r{index}")  # type: ignore[arg-type]


def retrieved(chunk_id: str, text: str) -> RetrievedChunk:
    chunk = Chunk(
        chunk_id=chunk_id,
        firm_name="Acme",
        doc_id="acme",
        doc_type="part2a",
        adv_item=5,
        is_toc=False,
        item_title="Fees",
        page_start=1,
        page_end=1,
        text=text,
        token_count=5,
    )
    return RetrievedChunk(chunk=chunk)


SENTENCES = [sentence("a"), sentence("b"), sentence("c"), sentence("d")]


def test_unsupported_sentences_are_removed_and_partial_ones_kept() -> None:
    results = [
        result(1, "supported"),
        result(2, "partial"),
        result(3, "unsupported"),
        result(4, "supported"),
    ]
    outcome = apply_verdicts(SENTENCES, results, max_drop_ratio=0.5)
    assert [s.text for s in outcome.kept] == ["a", "b", "d"]
    assert [s.text for s in outcome.removed] == ["c"]
    assert [r.verdict for r in outcome.verification] == [
        "supported",
        "partial",
        "unsupported",
        "supported",
    ]
    assert outcome.rejected is False and outcome.rejection_message is None


def test_results_out_of_order_are_aligned_by_sentence_index() -> None:
    results = [result(2, "unsupported"), result(1, "supported")]
    outcome = apply_verdicts(SENTENCES[:2], results, max_drop_ratio=0.5)
    assert [s.text for s in outcome.kept] == ["a"]
    assert [s.text for s in outcome.removed] == ["b"]


def test_drop_ratio_exactly_at_the_limit_is_not_rejected() -> None:
    results = [
        result(1, "unsupported"),
        result(2, "unsupported"),
        result(3, "supported"),
        result(4, "supported"),
    ]
    assert apply_verdicts(SENTENCES, results, max_drop_ratio=0.5).rejected is False


def test_drop_ratio_above_the_limit_is_rejected_with_a_message() -> None:
    results = [
        result(1, "unsupported"),
        result(2, "unsupported"),
        result(3, "unsupported"),
        result(4, "supported"),
    ]
    outcome = apply_verdicts(SENTENCES, results, max_drop_ratio=0.5)
    assert outcome.rejected is True
    assert "3 of 4" in (outcome.rejection_message or "")
    assert len(outcome.removed) == 3  # removed sentences are still reported


def test_everything_removed_is_rejected_even_at_a_permissive_ratio() -> None:
    results = [result(1, "unsupported"), result(2, "unsupported")]
    assert apply_verdicts(SENTENCES[:2], results, max_drop_ratio=1.0).rejected is True


@pytest.mark.parametrize("indices", [[1], [1, 2, 2], [0, 1], [2, 3], [1, 2, 3]])
def test_verdicts_that_do_not_cover_the_sentences_raise(indices: list[int]) -> None:
    with pytest.raises(VerifierError, match="expected 1..2"):
        apply_verdicts(SENTENCES[:2], [result(i, "supported") for i in indices], 0.5)


def test_user_message_numbers_from_one_and_includes_only_cited_chunk_text() -> None:
    chunks = [
        retrieved("c1", "TEXT ONE"),
        retrieved("c2", "TEXT TWO"),
        retrieved("c3", "TEXT THREE"),
    ]
    message = build_user_message([sentence("first", "c1"), sentence("second", "c2", "c3")], chunks)
    assert message.index("Sentence 1: first") < message.index("TEXT ONE")
    assert "Sentence 2: second" in message
    assert "TEXT TWO" in message and "TEXT THREE" in message
    assert message.count("TEXT ONE") == 1


def test_user_message_rejects_a_citation_to_an_unretrieved_chunk() -> None:
    with pytest.raises(VerifierError, match="nope"):
        build_user_message([sentence("x", "nope")], [retrieved("c1", "t")])


class FakeLLM:
    def __init__(self, output: VerifierOutput) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def complete_structured(
        self, model: str, system: str, user: str, output_model: type, trace: Trace, node: str
    ) -> VerifierOutput:
        self.calls.append({"model": model, "system": system, "user": user, "node": node})
        trace.events.append(TraceEvent(node=node, started_at=datetime.now(UTC)))
        return self.output


def test_verifier_makes_one_batched_call_and_logs_counts_on_its_event() -> None:
    llm = FakeLLM(VerifierOutput(results=[result(1, "supported"), result(2, "unsupported")]))
    settings = Settings(anthropic_api_key="sk-test", verifier_model="verifier-x")
    verifier = Verifier(settings, llm)  # type: ignore[arg-type]
    trace = Trace(query_id="t")
    outcome = verifier.verify(
        [sentence("a", "c1"), sentence("b", "c1")], [retrieved("c1", "text")], trace
    )
    assert len(llm.calls) == 1
    assert llm.calls[0]["model"] == "verifier-x"
    assert llm.calls[0]["node"] == "verify"
    assert "Sentence 1: a" in llm.calls[0]["user"] and "Sentence 2: b" in llm.calls[0]["user"]
    assert [s.text for s in outcome.removed] == ["b"]
    detail = trace.events[-1].detail
    assert (detail["sentences_checked"], detail["sentences_removed"]) == (2, 1)
    assert detail["sentences_partial"] == 0 and detail["rejected"] is False


def test_verifier_uses_the_configured_drop_ratio() -> None:
    llm = FakeLLM(VerifierOutput(results=[result(1, "supported"), result(2, "unsupported")]))
    settings = Settings(anthropic_api_key="sk-test", verifier_max_drop_ratio=0.25)
    outcome = Verifier(settings, llm).verify(  # type: ignore[arg-type]
        [sentence("a", "c1"), sentence("b", "c1")], [retrieved("c1", "t")], Trace(query_id="t")
    )
    assert outcome.rejected is True
