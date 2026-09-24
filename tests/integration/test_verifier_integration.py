"""The verifier against the real API: a fabricated number must not survive."""

import pytest

from agentguard.agents.generator import Generator
from agentguard.config import Settings
from agentguard.models import CitedSentence, GeneratorOutput, RetrievedChunk, Trace
from agentguard.pipeline import Pipeline

QUESTION = "What is Savvy's minimum account size?"
FABRICATED = "Savvy's minimum account size is $750,000 for all clients, with no exceptions."


@pytest.mark.integration
def test_verifier_removes_a_fabricated_number_the_generator_slipped_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_generate = Generator.generate

    def generate_with_fabrication(
        self: Generator, question: str, retrieved: list[RetrievedChunk], trace: Trace
    ) -> GeneratorOutput:
        output = real_generate(self, question, retrieved, trace)
        cited = output.sentences[0].citations[0]  # a real chunk, so the citation is valid
        fabricated = CitedSentence(text=FABRICATED, citations=[cited])
        return output.model_copy(update={"sentences": [*output.sentences, fabricated]})

    monkeypatch.setattr(Generator, "generate", generate_with_fabrication)
    # Cache off: assert on a real verifier call. Verifier on, and permissive enough that one
    # fabricated sentence among the real ones is removed rather than rejecting the answer.
    settings = Settings(enable_llm_cache=False, enable_verifier=True, verifier_max_drop_ratio=0.9)
    answer, trace = Pipeline.from_settings(settings).run(QUESTION)

    assert answer.refused is False, answer.refusal_message
    assert FABRICATED in [s.text for s in answer.removed_sentences]
    assert FABRICATED not in [s.text for s in answer.sentences]
    assert "750,000" not in " ".join(s.text for s in answer.sentences)
    assert any("500,000" in s.text for s in answer.sentences)  # the real answer survives
    assert len(answer.verification) == len(answer.sentences) + len(answer.removed_sentences)
    verify_event = next(e for e in trace.events if e.node == "verify")
    assert verify_event.cost_usd > 0
