import pytest
from pydantic import BaseModel

from agentguard.config import Settings
from agentguard.llm import LLMClient
from agentguard.models import Trace


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
