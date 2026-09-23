import pytest
from pydantic import BaseModel

from agentguard.config import Settings
from agentguard.llm import LLMClient
from agentguard.models import CitedSentence, Trace


class Arithmetic(BaseModel):
    """The result of a small arithmetic problem."""

    answer: int


@pytest.mark.integration
def test_real_structured_call_returns_valid_output_and_usage() -> None:
    settings = Settings(enable_llm_cache=False)
    client = LLMClient(settings)
    trace = Trace(query_id="integration")
    result = client.complete_structured(
        settings.generator_model,
        "You are a calculator.",
        "What is 17 + 25?",
        Arithmetic,
        trace,
        "integration",
    )
    assert result.answer == 42
    event = trace.events[0]
    assert event.input_tokens > 0
    assert event.output_tokens > 0
    assert event.cost_usd > 0
    assert event.detail["cached"] is False


class CitedAnswer(BaseModel):
    """An answer as a list of sentences, each citing the chunk_ids that support it."""

    sentences: list[CitedSentence]


CONTEXT = """[acme-p7-0] Acme Advisors | Item 5: Fees and Compensation
Acme charges an annual asset-based fee of 1.25% on the first $1 million.

[acme-p9-1] Acme Advisors | Item 15: Custody
Acme does not have custody of client assets, except for fee deduction."""


@pytest.mark.integration
def test_real_call_with_nested_defs_schema_validates() -> None:
    schema = CitedAnswer.model_json_schema()
    assert "$defs" in schema and "CitedSentence" in schema["$defs"]

    settings = Settings(enable_llm_cache=False)
    trace = Trace(query_id="integration-nested")
    result = LLMClient(settings).complete_structured(
        settings.generator_model,
        "Answer only from the chunks. Every sentence must cite one or more chunk_ids.",
        f"{CONTEXT}\n\nQuestion: What fee does Acme charge, and does it have custody?",
        CitedAnswer,
        trace,
        "integration",
    )
    assert isinstance(result, CitedAnswer)
    assert len(result.sentences) >= 1
    assert all(isinstance(s, CitedSentence) for s in result.sentences)
    cited = {c for s in result.sentences for c in s.citations}
    assert cited == {"acme-p7-0", "acme-p9-1"}
    assert trace.events[0].detail["attempts"] == 1


@pytest.mark.integration
def test_real_call_sends_temperature_to_model_that_accepts_it() -> None:
    settings = Settings(enable_llm_cache=False)
    trace = Trace(query_id="integration-temperature")
    result = LLMClient(settings).complete_structured(
        settings.policy_model,
        "You are a calculator.",
        "What is 17 + 25?",
        Arithmetic,
        trace,
        "integration",
    )
    assert result.answer == 42
    assert trace.events[0].detail["temperature"] == settings.llm_temperature
