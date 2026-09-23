"""The only place that talks to the Anthropic API.

Provides structured output via forced tool use, rate-limit retries, an on-disk
response cache, and token/cost accounting into the per-query trace.
"""

import hashlib
import json
import logging
from typing import Any, TypeVar

import anthropic
import diskcache
from anthropic.types import Message, ToolParam
from pydantic import BaseModel, ValidationError
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agentguard.config import MODEL_PRICES_PER_MILLION_TOKENS, Settings
from agentguard.models import Trace, TraceEvent
from agentguard.trace import trace_node

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

TOOL_NAME = "emit_structured_output"
RETRYABLE_ERRORS = (anthropic.RateLimitError, anthropic.OverloadedError)


class LLMError(Exception):
    """Base class for errors raised by the LLM wrapper."""


class StructuredOutputError(LLMError):
    """The model's output failed schema validation, even after one corrective retry."""


class UnknownModelPriceError(LLMError):
    """A model has no entry in the price table, so its cost cannot be computed."""


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost of one call, from the per-million-token price table in config."""
    prices = MODEL_PRICES_PER_MILLION_TOKENS.get(model)
    if prices is None:
        known = sorted(MODEL_PRICES_PER_MILLION_TOKENS)
        raise UnknownModelPriceError(
            f"No price for model {model!r}. Add it to config. Known: {known}"
        )
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


def cache_key(model: str, system: str, user: str, schema: dict[str, Any]) -> str:
    """Stable hash of everything that determines a structured response."""
    payload = json.dumps([model, system, user, schema], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_tool(output_model: type[BaseModel]) -> ToolParam:
    description = (output_model.__doc__ or "").strip() or f"Return a {output_model.__name__}."
    return {
        "name": TOOL_NAME,
        "description": description,
        "input_schema": output_model.model_json_schema(),
    }


def _parse_response(response: Message, output_model: type[T]) -> tuple[T | None, str]:
    """Validate the forced tool call. Returns (model, "") or (None, error text)."""
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            try:
                return output_model.model_validate(block.input), ""
            except ValidationError as exc:
                return None, str(exc)
    return None, f"No {TOOL_NAME} tool call in response (stop_reason={response.stop_reason})."


def _correction_message(user: str, error: str) -> str:
    return (
        f"{user}\n\n"
        f"Your previous {TOOL_NAME} call failed schema validation:\n{error}\n"
        f"Call {TOOL_NAME} again with input that satisfies the schema."
    )


class LLMClient:
    """Wrapper around `anthropic.Anthropic`; every LLM call in the project goes through here."""

    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        self._settings = settings
        # SDK-level retries are disabled so tenacity is the single, visible retry policy.
        self._client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(), max_retries=0
        )
        self._cache = (
            diskcache.Cache(str(settings.cache_dir / "llm")) if settings.enable_llm_cache else None
        )
        self._retry_wait = wait_exponential(multiplier=1, min=1, max=30)

    def complete_structured(
        self,
        model: str,
        system: str,
        user: str,
        output_model: type[T],
        trace: Trace,
        node_name: str,
    ) -> T:
        """Get a validated `output_model` from `model`, recorded as one event in `trace`.

        Uses a single tool forced via `tool_choice`. On validation failure it retries
        once with the error appended, then raises `StructuredOutputError`.
        Cache hits cost 0 and are flagged `cached=True` in the event detail.
        """
        schema = output_model.model_json_schema()
        key = cache_key(model, system, user, schema)
        with trace_node(trace, node_name) as event:
            event.detail["model"] = model
            if self._cache is not None:
                cached = self._cache.get(key)
                if cached is not None:
                    event.detail["cached"] = True
                    return output_model.model_validate(cached)
            event.detail["cached"] = False
            result = self._complete_with_correction(model, system, user, output_model, event)
            if self._cache is not None:
                self._cache.set(key, result.model_dump(mode="json"))
            return result

    def _complete_with_correction(
        self, model: str, system: str, user: str, output_model: type[T], event: TraceEvent
    ) -> T:
        tool = _build_tool(output_model)
        message = user
        errors: list[str] = []
        for attempt in (1, 2):
            event.detail["attempts"] = attempt
            response = self._create(model, system, message, tool)
            self._record_usage(event, model, response)
            result, error = _parse_response(response, output_model)
            if result is not None:
                return result
            logger.warning("Structured output invalid (attempt %d, %s): %s", attempt, model, error)
            errors.append(error)
            message = _correction_message(user, error)
        raise StructuredOutputError(
            f"{output_model.__name__} from {model} failed validation twice. "
            f"Last error:\n{errors[-1]}"
        )

    def _create(self, model: str, system: str, user: str, tool: ToolParam) -> Message:
        """One API call, retried with exponential backoff on rate limit / overload only."""
        retrying = Retrying(
            retry=retry_if_exception_type(RETRYABLE_ERRORS),
            wait=self._retry_wait,
            stop=stop_after_attempt(self._settings.llm_retry_attempts),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        return retrying(
            self._client.messages.create,
            model=model,
            max_tokens=self._settings.llm_max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        )

    @staticmethod
    def _record_usage(event: TraceEvent, model: str, response: Message) -> None:
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        event.input_tokens += input_tokens
        event.output_tokens += output_tokens
        event.cost_usd += compute_cost_usd(model, input_tokens, output_tokens)
