"""Decomposer with a fake LLM client (no network)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from agentguard.agents.decomposer import Decomposer, DecompositionOutput, clean_sub_queries
from agentguard.config import Settings
from agentguard.models import Trace, TraceEvent

QUESTION = "What does Acme charge, and has it faced any SEC action?"


class FakeLLM:
    def __init__(self, sub_queries: list[str]) -> None:
        self.sub_queries = sub_queries
        self.calls: list[dict[str, Any]] = []

    def complete_structured(
        self, model: str, system: str, user: str, output_model: Any, trace: Trace, node_name: str
    ) -> DecompositionOutput:
        self.calls.append({"model": model, "system": system, "user": user, "node": node_name})
        trace.events.append(TraceEvent(node=node_name, started_at=datetime.now(UTC), duration_ms=1))
        return DecompositionOutput(sub_queries=self.sub_queries)


def decomposer(sub_queries: list[str]) -> tuple[Decomposer, FakeLLM]:
    llm = FakeLLM(sub_queries)
    return Decomposer(Settings(anthropic_api_key="sk-test"), llm), llm  # type: ignore[arg-type]


def test_returns_the_llm_sub_queries_and_records_them_on_the_event() -> None:
    d, _ = decomposer(["Acme annual fee", "Acme SEC enforcement action"])
    trace = Trace(query_id="q")
    expected = ["Acme annual fee", "Acme SEC enforcement action"]
    assert d.decompose(QUESTION, trace) == expected
    assert trace.events[-1].detail["sub_queries"] == expected


def test_uses_the_policy_model_and_sends_only_the_question() -> None:
    d, llm = decomposer([QUESTION])
    d.decompose(QUESTION, Trace(query_id="q"))
    call = llm.calls[0]
    assert call["model"] == "claude-haiku-4-5-20251001"
    assert call["user"] == QUESTION and call["node"] == "decompose"
    assert "1 to 3" in call["system"]


def test_single_topic_question_comes_back_unchanged() -> None:
    question = "What is Savvy's minimum account size?"
    d, _ = decomposer([question])
    assert d.decompose(question, Trace(query_id="q")) == [question]


def test_schema_allows_one_to_three_sub_queries() -> None:
    with pytest.raises(ValidationError):
        DecompositionOutput(sub_queries=[])
    with pytest.raises(ValidationError):
        DecompositionOutput(sub_queries=["a", "b", "c", "d"])
    schema = DecompositionOutput.model_json_schema()["properties"]["sub_queries"]
    assert schema["minItems"] == 1 and schema["maxItems"] == 3


def test_clean_drops_blanks_and_duplicates_keeping_order() -> None:
    assert clean_sub_queries("q", [" a ", "A", "", "b"]) == ["a", "b"]


def test_clean_falls_back_to_the_question_when_nothing_is_usable() -> None:
    assert clean_sub_queries("the question", ["", "  "]) == ["the question"]


def test_a_single_reworded_query_is_replaced_by_the_original_question() -> None:
    d, _ = decomposer(["Acme SEC action"])
    trace = Trace(query_id="q")
    assert d.decompose(QUESTION, trace) == [QUESTION]
    assert trace.events[-1].detail["sub_queries"] == [QUESTION]
