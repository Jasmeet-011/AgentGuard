"""Graph topology and wiring, with fake retriever/generator (no network, no models)."""

import uuid

import pytest

from agentguard.agents.verifier import VerificationOutcome
from agentguard.config import Settings
from agentguard.graph import UNIMPLEMENTED_NODES, build_graph
from agentguard.models import (
    Answer,
    Chunk,
    CitedSentence,
    GeneratorOutput,
    PolicyDecision,
    RetrievedChunk,
    Trace,
    VerificationResult,
)


def settings(**overrides: object) -> Settings:
    """Verifier, decomposition and policy guard off unless a test turns them on: most tests here are about the baseline graph."""
    flags = {
        "enable_verifier": False,
        "enable_decomposition": False,
        "enable_policy_guard": False,
    } | overrides
    return Settings(anthropic_api_key="sk-test", **flags)  # type: ignore[arg-type]


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
        self.sub_queries: list[str] | None = None

    def retrieve(
        self,
        query: str,
        trace: Trace,
        mode: str | None = None,
        sub_queries: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        self.calls.append(query)
        self.sub_queries = sub_queries
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


class FakeVerifier:
    """Returns a canned outcome and records what it was asked to verify."""

    def __init__(self, outcome: VerificationOutcome | None = None) -> None:
        self.outcome = outcome
        self.calls: list[list[CitedSentence]] = []

    def verify(
        self, sentences: list[CitedSentence], retrieved: list[RetrievedChunk], trace: Trace
    ) -> VerificationOutcome:
        self.calls.append(sentences)
        assert self.outcome is not None
        return self.outcome


class FakePolicyGuard:
    """Returns a canned category and a message naming it."""

    def __init__(self, category: str = "allowed") -> None:
        self.category = category
        self.calls: list[str] = []

    def check(self, question: str, trace: Trace) -> PolicyDecision:
        self.calls.append(question)
        return PolicyDecision(category=self.category, reason="canned")  # type: ignore[arg-type]

    def refusal_message(self, decision: PolicyDecision) -> str:
        return f"blocked: {decision.category}"


class FakeDecomposer:
    """Returns canned sub-queries and records the questions it was asked to split."""

    def __init__(self, sub_queries: list[str] | None = None) -> None:
        self.sub_queries = sub_queries or ["sub one", "sub two"]
        self.calls: list[str] = []

    def decompose(self, question: str, trace: Trace) -> list[str]:
        self.calls.append(question)
        return self.sub_queries


@pytest.mark.parametrize("flag", sorted(UNIMPLEMENTED_NODES))
def test_enabling_an_unimplemented_node_raises_naming_its_milestone(flag: str) -> None:
    retrieved = [RetrievedChunk(chunk=make_chunk())]
    output = GeneratorOutput(refused=False, sentences=[])
    with pytest.raises(NotImplementedError) as exc_info:
        build_graph(
            settings(**{flag: True}),
            FakeRetriever(retrieved),
            FakeGenerator(output),
            FakeVerifier(),
            FakeDecomposer(),
            FakePolicyGuard(),
        )  # type: ignore[arg-type]
    assert flag in str(exc_info.value)
    assert UNIMPLEMENTED_NODES[flag] in str(exc_info.value)


def test_default_settings_build_without_raising() -> None:
    retrieved = [RetrievedChunk(chunk=make_chunk())]
    output = GeneratorOutput(refused=False, sentences=[])
    graph = build_graph(
        settings(),
        FakeRetriever(retrieved),
        FakeGenerator(output),
        FakeVerifier(),
        FakeDecomposer(),
        FakePolicyGuard(),
    )  # type: ignore[arg-type]
    assert graph is not None


def _invoke(
    retriever: FakeRetriever,
    generator: FakeGenerator,
    verifier: FakeVerifier | None = None,
    decomposer: FakeDecomposer | None = None,
    guard: FakePolicyGuard | None = None,
    **flags: object,
) -> Answer:
    graph = build_graph(
        settings(**flags),
        retriever,  # type: ignore[arg-type]
        generator,  # type: ignore[arg-type]
        verifier or FakeVerifier(),  # type: ignore[arg-type]
        decomposer or FakeDecomposer(),  # type: ignore[arg-type]
        guard or FakePolicyGuard(),  # type: ignore[arg-type]
    )
    trace = Trace(query_id=uuid.uuid4().hex)
    result = graph.invoke(
        {
            "question": "What fees does Acme charge?",
            "trace": trace,
            "policy_decision": None,
            "policy_message": None,
            "sub_queries": [],
            "retrieved": [],
            "generator_output": None,
            "verification": [],
            "removed_sentences": [],
            "verifier_rejected": False,
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


def _verdicts(*verdicts: str) -> list[VerificationResult]:
    return [
        VerificationResult(sentence_index=i, verdict=v, reason="r")  # type: ignore[arg-type]
        for i, v in enumerate(verdicts, start=1)
    ]


def _two_sentence_setup() -> tuple[FakeRetriever, FakeGenerator, list[CitedSentence]]:
    chunk = make_chunk()
    good = CitedSentence(text="Acme charges 1.25%.", citations=[chunk.chunk_id])
    bad = CitedSentence(text="Acme charges 9%.", citations=[chunk.chunk_id])
    retriever = FakeRetriever([RetrievedChunk(chunk=chunk)])
    generator = FakeGenerator(GeneratorOutput(refused=False, sentences=[good, bad]))
    return retriever, generator, [good, bad]


def test_verifier_off_never_calls_the_verifier() -> None:
    retriever, generator, sentences = _two_sentence_setup()
    verifier = FakeVerifier()
    answer = _invoke(retriever, generator, verifier, enable_verifier=False)
    assert verifier.calls == []
    assert answer.sentences == sentences
    assert answer.verification == [] and answer.removed_sentences == []


def test_verifier_on_removes_unsupported_sentences_and_records_them() -> None:
    retriever, generator, (good, bad) = _two_sentence_setup()
    outcome = VerificationOutcome(
        kept=[good],
        removed=[bad],
        verification=_verdicts("supported", "unsupported"),
        rejected=False,
    )
    verifier = FakeVerifier(outcome)
    answer = _invoke(retriever, generator, verifier, enable_verifier=True)
    assert verifier.calls == [[good, bad]]
    assert answer.refused is False
    assert answer.sentences == [good]
    assert answer.removed_sentences == [bad]
    assert [v.verdict for v in answer.verification] == ["supported", "unsupported"]
    assert [v.verdict for v in answer.kept_verification()] == ["supported"]


def test_verifier_rejection_becomes_a_refusal_with_its_own_reason() -> None:
    retriever, generator, (good, bad) = _two_sentence_setup()
    outcome = VerificationOutcome(
        kept=[],
        removed=[good, bad],
        verification=_verdicts("unsupported", "unsupported"),
        rejected=True,
        rejection_message="rejected",
    )
    answer = _invoke(retriever, generator, FakeVerifier(outcome), enable_verifier=True)
    assert answer.refused is True
    assert answer.refusal_reason == "verifier_rejected"
    assert answer.refusal_message == "rejected"
    assert answer.sentences == []
    assert answer.removed_sentences == [good, bad]


def test_generator_refusal_skips_the_verifier() -> None:
    verifier = FakeVerifier()
    generator = FakeGenerator(GeneratorOutput(refused=True, refusal_message="nothing relevant"))
    answer = _invoke(FakeRetriever([]), generator, verifier, enable_verifier=True)
    assert verifier.calls == []
    assert answer.refusal_reason == "insufficient_evidence"


def test_topology_gains_a_verify_node_only_when_enabled() -> None:
    args = (
        FakeRetriever([]),
        FakeGenerator(GeneratorOutput(refused=False)),
        FakeVerifier(),
        FakeDecomposer(),
        FakePolicyGuard(),
    )
    off = build_graph(settings(enable_verifier=False), *args)  # type: ignore[arg-type]
    on = build_graph(settings(enable_verifier=True), *args)  # type: ignore[arg-type]
    assert "verify" not in off.get_graph().nodes
    assert "verify" in on.get_graph().nodes


def test_decomposition_off_never_calls_the_decomposer_and_retrieves_the_question() -> None:
    retriever = FakeRetriever([RetrievedChunk(chunk=make_chunk())])
    decomposer = FakeDecomposer()
    _invoke(retriever, FakeGenerator(GeneratorOutput(refused=True)), decomposer=decomposer)
    assert decomposer.calls == []
    assert retriever.sub_queries is None


def test_decomposition_on_passes_sub_queries_to_retriever_but_generates_from_question() -> None:
    retriever = FakeRetriever([RetrievedChunk(chunk=make_chunk())])
    generator = FakeGenerator(GeneratorOutput(refused=True))
    decomposer = FakeDecomposer(["fees", "SEC action"])
    _invoke(retriever, generator, decomposer=decomposer, enable_decomposition=True)
    assert decomposer.calls == ["What fees does Acme charge?"]
    assert retriever.sub_queries == ["fees", "SEC action"]
    assert retriever.calls == ["What fees does Acme charge?"]  # the firm filter comes from this
    assert generator.calls[0][0] == "What fees does Acme charge?"


def test_topology_gains_a_decompose_node_only_when_enabled() -> None:
    args = (
        FakeRetriever([]),
        FakeGenerator(GeneratorOutput(refused=False)),
        FakeVerifier(),
        FakeDecomposer(),
        FakePolicyGuard(),
    )
    off = build_graph(settings(enable_decomposition=False), *args)  # type: ignore[arg-type]
    on = build_graph(settings(enable_decomposition=True), *args)  # type: ignore[arg-type]
    assert "decompose" not in off.get_graph().nodes
    assert "decompose" in on.get_graph().nodes


def test_policy_guard_off_never_calls_the_guard() -> None:
    guard = FakePolicyGuard("personalized_advice")
    generator = FakeGenerator(GeneratorOutput(refused=True))
    _invoke(FakeRetriever([]), generator, guard=guard)
    assert guard.calls == []
    assert generator.calls  # the pipeline ran even though the fake guard would have blocked


@pytest.mark.parametrize("category", ["personalized_advice", "pii_request", "out_of_scope"])
def test_blocked_question_skips_everything_and_refuses_with_reason_policy(category: str) -> None:
    retriever = FakeRetriever([RetrievedChunk(chunk=make_chunk())])
    generator = FakeGenerator(GeneratorOutput(refused=False))
    decomposer = FakeDecomposer()
    verifier = FakeVerifier()
    answer = _invoke(
        retriever,
        generator,
        verifier,
        decomposer,
        FakePolicyGuard(category),
        enable_policy_guard=True,
        enable_decomposition=True,
        enable_verifier=True,
    )
    assert (retriever.calls, generator.calls, decomposer.calls, verifier.calls) == ([], [], [], [])
    assert answer.refused and answer.refusal_reason == "policy"
    assert answer.refusal_message == f"blocked: {category}"
    assert answer.sentences == [] and answer.retrieved == []


def test_allowed_question_runs_the_rest_of_the_pipeline() -> None:
    sentence = CitedSentence(text="Acme charges 1.25%.", citations=["acme-p7-0"])
    guard = FakePolicyGuard("allowed")
    retriever = FakeRetriever([RetrievedChunk(chunk=make_chunk())])
    generator = FakeGenerator(GeneratorOutput(refused=False, sentences=[sentence]))
    decomposer = FakeDecomposer(["a", "b"])
    answer = _invoke(
        retriever,
        generator,
        decomposer=decomposer,
        guard=guard,
        enable_policy_guard=True,
        enable_decomposition=True,
    )
    assert guard.calls == ["What fees does Acme charge?"]
    assert decomposer.calls and retriever.calls and generator.calls
    assert not answer.refused and answer.sentences == [sentence]


def test_policy_guard_node_exists_only_when_enabled() -> None:
    args = (
        FakeRetriever([]),
        FakeGenerator(GeneratorOutput(refused=False)),
        FakeVerifier(),
        FakeDecomposer(),
        FakePolicyGuard(),
    )
    off = build_graph(settings(enable_policy_guard=False), *args)  # type: ignore[arg-type]
    on = build_graph(settings(enable_policy_guard=True), *args)  # type: ignore[arg-type]
    assert "policy_guard" not in off.get_graph().nodes
    assert "policy_guard" in on.get_graph().nodes
