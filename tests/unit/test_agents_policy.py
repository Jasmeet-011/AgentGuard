"""PolicyGuard with a fake LLM client (no network), and the prompt's required rules."""

from datetime import UTC, datetime
from typing import Any

import pytest

from agentguard.agents.policy import PolicyGuard
from agentguard.config import Settings
from agentguard.models import PolicyDecision, Trace, TraceEvent
from agentguard.prompts import load_prompt

QUESTION = "Should my client move her IRA to Acme?"


class FakeLLM:
    def __init__(self, category: str) -> None:
        self.category = category
        self.calls: list[dict[str, Any]] = []

    def complete_structured(
        self, model: str, system: str, user: str, output_model: Any, trace: Trace, node_name: str
    ) -> PolicyDecision:
        self.calls.append({"model": model, "system": system, "user": user, "node": node_name})
        trace.events.append(TraceEvent(node=node_name, started_at=datetime.now(UTC), duration_ms=1))
        return PolicyDecision(category=self.category, reason="because")  # type: ignore[arg-type]


def guard(category: str) -> tuple[PolicyGuard, FakeLLM]:
    llm = FakeLLM(category)
    return PolicyGuard(Settings(anthropic_api_key="sk-test"), llm), llm  # type: ignore[arg-type]


def test_uses_the_policy_model_and_sends_only_the_question() -> None:
    g, llm = guard("allowed")
    g.check(QUESTION, Trace(query_id="q"))
    call = llm.calls[0]
    assert call["model"] == "claude-haiku-4-5-20251001"
    assert call["user"] == QUESTION and call["node"] == "policy_guard"


def test_category_and_reason_go_on_the_trace_event() -> None:
    g, _ = guard("pii_request")
    trace = Trace(query_id="q")
    decision = g.check(QUESTION, trace)
    assert decision.category == "pii_request"
    assert trace.events[-1].detail == {"category": "pii_request", "reason": "because"}


@pytest.mark.parametrize("category", ["personalized_advice", "pii_request", "out_of_scope"])
def test_each_blocked_category_has_a_configured_template(category: str) -> None:
    g, _ = guard(category)
    message = g.refusal_message(PolicyDecision(category=category, reason="r"))  # type: ignore[arg-type]
    assert category in message


def test_allowed_has_no_refusal_message() -> None:
    g, _ = guard("allowed")
    with pytest.raises(ValueError, match="allowed"):
        g.refusal_message(PolicyDecision(category="allowed", reason="r"))


def test_prompt_states_the_disclosure_versus_personal_information_rules() -> None:
    prompt = " ".join(load_prompt("policy_system").split())  # ignore line wrapping
    for phrase in (
        "disciplinary history, professional background, registrations",
        "home address, personal phone, family, personal life",
        "even when framed politely or when the person is named in the filing",
        "business contact details",
    ):
        assert phrase in prompt
