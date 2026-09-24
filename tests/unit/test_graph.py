"""Graph topology and wiring, with fake retriever/generator (no network, no models)."""

import uuid

import pytest

from agentguard.config import Settings
from agentguard.graph import UNIMPLEMENTED_NODES, build_graph
from agentguard.models import (
    Answer,
    Chunk,
    CitedSentence,
    GeneratorOutput,
    RetrievedChunk,
    Trace,
)


def settings(**overrides: object) -> Settings:
    return Settings(anthropic_api_key="sk-test", **overrides)


def make_chunk(chunk_id: str = "acme-p7-0") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        firm_name="Acme",
        doc_id="acme",
        doc_type="part2a",
        adv_item=5,
        is_toc=False,
        item_title="Fees and Compensation",
        page_start=7,
        page_end=7,
        text="Acme | Item 5: Fees and Compensation\nWe charge 1.25% annually.",
        token_count=10,
    )


class FakeRetriever:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.calls: list[str] = []

    def retrieve(self, query: str, trace: Trace, mode: str | None = None) -> list[RetrievedChunk]:
        self.calls.append(query)
        return self.results


class FakeGenerator:
    def __init__(self, output: GeneratorOutput) -> None:
        self.output = output
        self.calls: list[tuple[str, list[RetrievedChunk]]] = []

    def generate(
        self, question: str, retrieved: list[RetrievedChunk], trace: Trace
    ) -> GeneratorOutput:
        self.calls.append((question, retrieved))
        return self.output


@pytest.mark.parametrize("flag", sorted(UNIMPLEMENTED_NODES))
def test_enabling_an_unimplemented_node_raises_naming_its_milestone(flag: str) -> None:
    retrieved = [RetrievedChunk(chunk=make_chunk())]
    output = GeneratorOutput(refused=False, sentences=[])
    with pytest.raises(NotImplementedError) as exc_info:
        build_graph(settings(**{flag: True}), FakeRetriever(retrieved), FakeGenerator(output))  # type: ignore[arg-type]
    assert flag in str(exc_info.value)
    assert UNIMPLEMENTED_NODES[flag] in str(exc_info.value)


def test_default_settings_build_without_raising() -> None:
    retrieved = [RetrievedChunk(chunk=make_chunk())]
    output = GeneratorOutput(refused=False, sentences=[])
    graph = build_graph(settings(), FakeRetriever(retrieved), FakeGenerator(output))  # type: ignore[arg-type]
    assert graph is not None


def _invoke(retriever: FakeRetriever, generator: FakeGenerator) -> Answer:
    graph = build_graph(settings(), retriever, generator)  # type: ignore[arg-type]
    trace = Trace(query_id=uuid.uuid4().hex)
    result = graph.invoke(
        {
            "question": "What fees does Acme charge?",
            "trace": trace,
            "retrieved": [],
            "generator_output": None,
            "answer": None,
        }
    )
    return result["answer"]


def test_graph_returns_valid_answer_from_mocked_retriever_and_generator() -> None:
    chunk = make_chunk()
    retriever = FakeRetriever([RetrievedChunk(chunk=chunk)])
    sentence = CitedSentence(text="Acme charges 1.25%.", citations=[chunk.chunk_id])
    generator = FakeGenerator(GeneratorOutput(refused=False, sentences=[sentence]))

    answer = _invoke(retriever, generator)

    assert isinstance(answer, Answer)
    assert answer.refused is False
    assert answer.sentences == [sentence]
    assert answer.retrieved == [RetrievedChunk(chunk=chunk)]
    assert retriever.calls == ["What fees does Acme charge?"]
    assert generator.calls[0][0] == "What fees does Acme charge?"


def test_refusal_with_no_refusal_kind_defaults_to_insufficient_evidence() -> None:
    retriever = FakeRetriever([])
    generator = FakeGenerator(
        GeneratorOutput(refused=True, refusal_message="No chunks are relevant.")
    )

    answer = _invoke(retriever, generator)

    assert answer.refused is True
    assert answer.refusal_reason == "insufficient_evidence"
    assert answer.refusal_message == "No chunks are relevant."
    assert answer.sentences == []


def test_refusal_kind_insufficient_evidence_maps_to_same_reason() -> None:
    retriever = FakeRetriever([])
    generator = FakeGenerator(
        GeneratorOutput(
            refused=True,
            refusal_kind="insufficient_evidence",
            refusal_message="No chunks are relevant.",
        )
    )

    answer = _invoke(retriever, generator)

    assert answer.refusal_reason == "insufficient_evidence"


def test_refusal_kind_advice_request_maps_to_policy_reason() -> None:
    retriever = FakeRetriever([])
    generator = FakeGenerator(
        GeneratorOutput(
            refused=True,
            refusal_kind="advice_request",
            refusal_message="This tool does not give personalized investment advice.",
        )
    )

    answer = _invoke(retriever, generator)

    assert answer.refused is True
    assert answer.refusal_reason == "policy"
    assert answer.refusal_message == "This tool does not give personalized investment advice."


def test_partial_note_carried_into_answer() -> None:
    chunk = make_chunk()
    retriever = FakeRetriever([RetrievedChunk(chunk=chunk)])
    sentence = CitedSentence(text="Acme charges 1.25%.", citations=[chunk.chunk_id])
    generator = FakeGenerator(
        GeneratorOutput(refused=False, sentences=[sentence], partial_note="Custody is not covered.")
    )

    answer = _invoke(retriever, generator)

    assert answer.partial_note == "Custody is not covered."
