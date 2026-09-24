"""Generator behavior with a fake LLM client (no network)."""

from datetime import UTC, datetime
from typing import Any

from agentguard.agents.generator import Generator
from agentguard.config import Settings
from agentguard.models import (
    Chunk,
    CitedSentence,
    GeneratorOutput,
    RetrievedChunk,
    Trace,
    TraceEvent,
)


def make_chunk(chunk_id: str, firm_name: str = "Acme", adv_item: int | None = 5) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        firm_name=firm_name,
        doc_id=firm_name.lower(),
        doc_type="part2a",
        adv_item=adv_item,
        is_toc=False,
        item_title="Fees and Compensation" if adv_item == 5 else None,
        page_start=7,
        page_end=7,
        text=f"{firm_name} | Item 5: Fees and Compensation\nWe charge 1.25% annually.",
        token_count=10,
    )


class FakeLLMClient:
    """Records the (model, system, user) it was called with and returns a canned output."""

    def __init__(self, output: GeneratorOutput) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def complete_structured(
        self, model: str, system: str, user: str, output_model: type, trace: Trace, node_name: str
    ) -> GeneratorOutput:
        self.calls.append({"model": model, "system": system, "user": user, "node": node_name})
        trace.events.append(TraceEvent(node=node_name, started_at=datetime.now(UTC)))
        return self.output


def settings() -> Settings:
    return Settings(anthropic_api_key="sk-test")


def retrieved(chunk: Chunk) -> RetrievedChunk:
    return RetrievedChunk(chunk=chunk)


def test_context_block_includes_firm_doc_type_item_and_pages() -> None:
    output = GeneratorOutput(refused=True, refusal_message="nothing relevant")
    llm = FakeLLMClient(output)
    generator = Generator(settings(), llm)  # type: ignore[arg-type]
    chunk = make_chunk("acme-p7-0")
    generator.generate("What fees?", [retrieved(chunk)], Trace(query_id="q1"))

    user = llm.calls[0]["user"]
    assert "chunk_id: acme-p7-0" in user
    assert "Firm: Acme" in user
    assert "Doc type: part2a" in user
    assert "Item: 5 (Fees and Compensation)" in user
    assert "Pages: 7-7" in user
    assert "We charge 1.25% annually." in user


def test_unlabeled_item_shown_as_unlabeled() -> None:
    output = GeneratorOutput(refused=True, refusal_message="nothing relevant")
    llm = FakeLLMClient(output)
    generator = Generator(settings(), llm)  # type: ignore[arg-type]
    chunk = make_chunk("acme-p2-0", adv_item=None)
    generator.generate("q", [retrieved(chunk)], Trace(query_id="q1"))
    assert "Item: unlabeled" in llm.calls[0]["user"]


def test_drops_citation_to_chunk_id_not_retrieved() -> None:
    output = GeneratorOutput(
        sentences=[CitedSentence(text="Acme charges 1.25%.", citations=["acme-p7-0", "fake-id"])],
        refused=False,
    )
    llm = FakeLLMClient(output)
    generator = Generator(settings(), llm)  # type: ignore[arg-type]
    chunk = make_chunk("acme-p7-0")
    trace = Trace(query_id="q1")

    result = generator.generate("What fees?", [retrieved(chunk)], trace)

    assert result.sentences == [CitedSentence(text="Acme charges 1.25%.", citations=["acme-p7-0"])]
    assert trace.events[-1].detail["invalid_citations_dropped"] == 1
    assert trace.events[-1].detail["sentences_dropped"] == 0


def test_drops_sentence_whose_only_citation_is_invalid() -> None:
    output = GeneratorOutput(
        sentences=[
            CitedSentence(text="Valid sentence.", citations=["acme-p7-0"]),
            CitedSentence(text="Fabricated sentence.", citations=["fake-id"]),
        ],
        refused=False,
    )
    llm = FakeLLMClient(output)
    generator = Generator(settings(), llm)  # type: ignore[arg-type]
    chunk = make_chunk("acme-p7-0")
    trace = Trace(query_id="q1")

    result = generator.generate("What fees?", [retrieved(chunk)], trace)

    assert [s.text for s in result.sentences] == ["Valid sentence."]
    assert trace.events[-1].detail["sentences_dropped"] == 1


def test_no_citations_dropped_leaves_detail_unset() -> None:
    output = GeneratorOutput(
        sentences=[CitedSentence(text="Valid.", citations=["acme-p7-0"])], refused=False
    )
    llm = FakeLLMClient(output)
    generator = Generator(settings(), llm)  # type: ignore[arg-type]
    chunk = make_chunk("acme-p7-0")
    trace = Trace(query_id="q1")

    generator.generate("What fees?", [retrieved(chunk)], trace)

    assert "invalid_citations_dropped" not in trace.events[-1].detail


def test_refusal_and_partial_note_pass_through_unchanged() -> None:
    output = GeneratorOutput(
        sentences=[CitedSentence(text="Acme charges 1.25%.", citations=["acme-p7-0"])],
        refused=False,
        partial_note="Custody is not covered by the provided chunks.",
    )
    llm = FakeLLMClient(output)
    generator = Generator(settings(), llm)  # type: ignore[arg-type]
    chunk = make_chunk("acme-p7-0")

    result = generator.generate("What fees and custody?", [retrieved(chunk)], Trace(query_id="q1"))

    assert result.partial_note == "Custody is not covered by the provided chunks."
    assert result.refused is False
