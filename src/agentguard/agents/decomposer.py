"""Query decomposition: split a multi-topic question into up to 3 self-contained sub-queries."""

import logging

from pydantic import BaseModel, Field

from agentguard.config import Settings
from agentguard.llm import LLMClient
from agentguard.models import Trace
from agentguard.prompts import load_prompt

logger = logging.getLogger(__name__)

DECOMPOSE_PROMPT = "decompose_system"
DECOMPOSE_NODE_NAME = "decompose"
MAX_SUB_QUERIES = 3


class DecompositionOutput(BaseModel):
    """1 to 3 search queries; a single-topic question comes back as itself."""

    sub_queries: list[str] = Field(min_length=1, max_length=MAX_SUB_QUERIES)


def clean_sub_queries(question: str, sub_queries: list[str]) -> list[str]:
    """Strip, drop blanks and case-insensitive duplicates (keeping order); never return empty.

    If nothing usable is left, the original question is the only query.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for query in (q.strip() for q in sub_queries):
        if query and query.lower() not in seen:
            seen.add(query.lower())
            cleaned.append(query)
    return cleaned or [question]


class Decomposer:
    """Splits questions into sub-queries with `settings.policy_model` (the cheap, fast model)."""

    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self._settings = settings
        self._llm = llm

    def decompose(self, question: str, trace: Trace) -> list[str]:
        """Return 1 to 3 sub-queries for `question`; the sub-query count goes on the trace event."""
        output = self._llm.complete_structured(
            self._settings.policy_model,
            load_prompt(DECOMPOSE_PROMPT),
            question,
            DecompositionOutput,
            trace,
            DECOMPOSE_NODE_NAME,
        )
        assert isinstance(output, DecompositionOutput)
        sub_queries = clean_sub_queries(question, output.sub_queries)
        if len(sub_queries) == 1:
            sub_queries = [question]  # one topic: always the question itself, never a rewording
        trace.events[-1].detail["sub_queries"] = sub_queries
        if len(sub_queries) > 1:
            logger.info("Decomposed %r into %s", question, sub_queries)
        return sub_queries
