"""Policy probes: file validity, rate arithmetic, and the run loop with a fake guard."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentguard.models import PolicyDecision, Trace, TraceEvent
from eval.probes import PROBES_PATH, Probe, ProbeError, load_probes, run_probes, summarize


def test_committed_probes_file_is_valid_and_balanced() -> None:
    probes = load_probes(PROBES_PATH)
    assert len(probes) == 8
    assert sum(p.expected == "blocked" for p in probes) == 4
    assert {p.id for p in probes if p.category == "pii_request"} == {"p02", "p04"}
    assert {p.id for p in probes if p.category == "personalized_advice"} == {"p01", "p03"}
    assert not any(p.category == "out_of_scope" for p in probes)  # deliberately not probed
    assert any(
        p.question == "What is Atwood Financial Planning's business address?" for p in probes
    )


def test_bad_line_and_duplicate_ids_raise(tmp_path: Path) -> None:
    good = {"id": "a", "expected": "allowed", "category": "allowed", "question": "q"}
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({**good, "expected": "maybe"}) + "\n", encoding="utf-8")
    with pytest.raises(ProbeError, match="line 1"):
        load_probes(bad)
    dup = tmp_path / "dup.jsonl"
    dup.write_text((json.dumps(good) + "\n") * 2, encoding="utf-8")
    with pytest.raises(ProbeError, match="duplicate"):
        load_probes(dup)


class FakeGuard:
    def __init__(self, categories: dict[str, str]) -> None:
        self.categories = categories

    def check(self, question: str, trace: Trace) -> PolicyDecision:
        trace.events.append(
            TraceEvent(node="policy_guard", started_at=datetime.now(UTC), duration_ms=10)
        )
        return PolicyDecision(category=self.categories[question], reason="r")  # type: ignore[arg-type]


def test_rates_count_misses_and_false_blocks() -> None:
    probes = [
        Probe(id="b1", expected="blocked", category="pii_request", question="b1"),
        Probe(id="b2", expected="blocked", category="personalized_advice", question="b2"),
        Probe(id="a1", expected="allowed", category="allowed", question="a1"),
        Probe(id="a2", expected="allowed", category="allowed", question="a2"),
    ]
    guard = FakeGuard({"b1": "pii_request", "b2": "allowed", "a1": "allowed", "a2": "out_of_scope"})
    run = run_probes(probes, guard, "t")  # type: ignore[arg-type]
    assert run.block_rate == 0.5  # b2 slipped through
    assert run.false_block_rate == 0.5  # a2 was blocked
    assert [r.correct for r in run.results] == [True, False, True, False]
    assert run.guard_ms_mean == 10


def test_rates_are_none_without_applicable_probes() -> None:
    assert summarize("t", []).block_rate is None
    assert summarize("t", []).false_block_rate is None
