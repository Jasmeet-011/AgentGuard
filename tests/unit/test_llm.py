from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest
from pydantic import BaseModel
from tenacity import wait_none

from agentguard.config import Settings
from agentguard.llm import (
    TOOL_NAME,
    LLMClient,
    StructuredOutputError,
    UnknownModelPriceError,
    compute_cost_usd,
)
from agentguard.models import Trace

MODEL = "claude-sonnet-5"


class Capital(BaseModel):
    """The capital city of a country."""

    city: str
    population_millions: float


def fake_response(tool_input: Any, input_tokens: int = 100, output_tokens: int = 20) -> Any:
    block = SimpleNamespace(type="tool_use", name=TOOL_NAME, input=tool_input)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=[block], usage=usage, stop_reason="tool_use")


def make_client(tmp_path: Path, responses: list[Any], cache: bool = True) -> tuple[LLMClient, Any]:
    settings = Settings(anthropic_api_key="sk-test", cache_dir=tmp_path, enable_llm_cache=cache)
    sdk = MagicMock()
    sdk.messages.create.side_effect = responses
    client = LLMClient(settings, client=sdk)
    client._retry_wait = wait_none()
    return client, sdk


def call(client: LLMClient, trace: Trace, user: str = "Capital of France?") -> Capital:
    return client.complete_structured(MODEL, "Be terse.", user, Capital, trace, "generate")


def rate_limit_error() -> anthropic.RateLimitError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.RateLimitError(
        "rate limited", response=httpx.Response(429, request=request), body=None
    )


def test_returns_validated_model_and_records_usage(tmp_path: Path) -> None:
    client, sdk = make_client(
        tmp_path, [fake_response({"city": "Paris", "population_millions": 2.1})]
    )
    trace = Trace(query_id="q1")
    result = call(client, trace)
    assert result == Capital(city="Paris", population_millions=2.1)
    event = trace.events[0]
    assert event.node == "generate"
    assert (event.input_tokens, event.output_tokens) == (100, 20)
    assert event.cost_usd == pytest.approx(compute_cost_usd(MODEL, 100, 20))
    assert event.cost_usd > 0
    assert event.detail["cached"] is False
    kwargs = sdk.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert kwargs["tools"][0]["input_schema"] == Capital.model_json_schema()


def test_retries_once_with_error_appended_then_succeeds(tmp_path: Path) -> None:
    client, sdk = make_client(
        tmp_path,
        [
            fake_response({"city": "Paris"}),
            fake_response({"city": "Paris", "population_millions": 2.1}),
        ],
    )
    trace = Trace(query_id="q1")
    assert call(client, trace).city == "Paris"
    second_user = sdk.messages.create.call_args_list[1].kwargs["messages"][0]["content"]
    assert "failed schema validation" in second_user
    assert "population_millions" in second_user
    event = trace.events[0]
    assert event.detail["attempts"] == 2
    assert (event.input_tokens, event.output_tokens) == (200, 40)


def test_raises_clear_error_after_second_invalid_output(tmp_path: Path) -> None:
    client, sdk = make_client(tmp_path, [fake_response({"city": 1}), fake_response("not json")])
    trace = Trace(query_id="q1")
    with pytest.raises(StructuredOutputError, match="Capital from claude-sonnet-5 failed"):
        call(client, trace)
    assert sdk.messages.create.call_count == 2
    assert trace.events[0].input_tokens == 200


def test_missing_tool_call_counts_as_invalid(tmp_path: Path) -> None:
    text_only = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Paris")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        stop_reason="max_tokens",
    )
    client, _ = make_client(tmp_path, [text_only, text_only])
    with pytest.raises(StructuredOutputError, match="stop_reason=max_tokens"):
        call(client, Trace(query_id="q1"))


def test_cache_hit_returns_identical_object_with_zero_cost(tmp_path: Path) -> None:
    client, sdk = make_client(
        tmp_path, [fake_response({"city": "Paris", "population_millions": 2.1})]
    )
    trace = Trace(query_id="q1")
    first = call(client, trace)
    second = call(client, trace)
    assert second == first
    assert sdk.messages.create.call_count == 1
    hit = trace.events[1]
    assert hit.detail["cached"] is True
    assert (hit.cost_usd, hit.input_tokens, hit.output_tokens) == (0, 0, 0)


def test_cache_disabled_always_calls_api(tmp_path: Path) -> None:
    response = fake_response({"city": "Paris", "population_millions": 2.1})
    client, sdk = make_client(tmp_path, [response, response], cache=False)
    trace = Trace(query_id="q1")
    call(client, trace)
    call(client, trace)
    assert sdk.messages.create.call_count == 2


def test_different_prompt_is_a_cache_miss(tmp_path: Path) -> None:
    client, sdk = make_client(
        tmp_path,
        [
            fake_response({"city": "Paris", "population_millions": 2.1}),
            fake_response({"city": "Rome", "population_millions": 2.8}),
        ],
    )
    trace = Trace(query_id="q1")
    call(client, trace, "Capital of France?")
    assert call(client, trace, "Capital of Italy?").city == "Rome"
    assert sdk.messages.create.call_count == 2


def test_rate_limit_is_retried(tmp_path: Path) -> None:
    ok = fake_response({"city": "Paris", "population_millions": 2.1})
    client, sdk = make_client(tmp_path, [rate_limit_error(), ok])
    assert call(client, Trace(query_id="q1")).city == "Paris"
    assert sdk.messages.create.call_count == 2


def test_non_retryable_api_error_propagates_immediately(tmp_path: Path) -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    bad = anthropic.BadRequestError("bad", response=httpx.Response(400, request=request), body=None)
    client, sdk = make_client(tmp_path, [bad])
    with pytest.raises(anthropic.BadRequestError):
        call(client, Trace(query_id="q1"))
    assert sdk.messages.create.call_count == 1


def test_unknown_model_price_fails_loudly() -> None:
    with pytest.raises(UnknownModelPriceError, match="no-such-model"):
        compute_cost_usd("no-such-model", 1, 1)
