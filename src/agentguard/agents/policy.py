"""The policy guard: classifies a question before retrieval so advice and PII requests are blocked."""

import logging

from agentguard.config import Settings
from agentguard.llm import LLMClient
from agentguard.models import PolicyDecision, Trace
from agentguard.prompts import load_prompt

logger = logging.getLogger(__name__)

POLICY_PROMPT = "policy_system"
POLICY_NODE_NAME = "policy_guard"


class PolicyGuard:
    """Classifies questions with `settings.policy_model` (the cheap, fast model)."""

    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self._settings = settings
        self._llm = llm

    def check(self, question: str, trace: Trace) -> PolicyDecision:
        """Classify `question`; the category and reason go on the trace event's detail."""
        decision = self._llm.complete_structured(
            self._settings.policy_model,
            load_prompt(POLICY_PROMPT),
            question,
            PolicyDecision,
            trace,
            POLICY_NODE_NAME,
        )
        assert isinstance(decision, PolicyDecision)
        trace.events[-1].detail["category"] = decision.category
        trace.events[-1].detail["reason"] = decision.reason
        if decision.category != "allowed":
            logger.info("Blocked %r as %s: %s", question, decision.category, decision.reason)
        return decision

    def refusal_message(self, decision: PolicyDecision) -> str:
        """The configured refusal template for a blocked category. Raises for `allowed`."""
        try:
            return self._settings.policy_refusal_messages[decision.category]
        except KeyError:
            raise ValueError(f"No refusal message for category {decision.category!r}") from None
