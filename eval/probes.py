"""Adversarial policy probes: run the guard alone on `policy_probes.jsonl` and report rates.

Probes are about classification, so the guard is called directly (no retrieval or
generation): "blocked" means any category other than `allowed`.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentguard.agents.policy import PolicyGuard
from agentguard.models import Trace
from agentguard.trace import event_values

PROBES_PATH = Path(__file__).parent / "policy_probes.jsonl"


class ProbeError(Exception):
    """The probes file is invalid."""


class Probe(BaseModel):
    """One probe question and what the guard should do with it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    expected: Literal["blocked", "allowed"]
    category: Literal["allowed", "personalized_advice", "pii_request", "out_of_scope"]
    question: str
    notes: str = ""


class ProbeResult(BaseModel):
    """The guard's decision on one probe."""

    id: str
    expected: str
    expected_category: str
    question: str
    category: str
    reason: str
    blocked: bool
    correct: bool
    guard_ms: float


class ProbeRun(BaseModel):
    """All probe results plus the block and false-block rates."""

    timestamp: str
    results: list[ProbeResult]
    block_rate: float | None  # of probes expected blocked, fraction blocked
    false_block_rate: float | None  # of probes expected allowed, fraction blocked
    guard_ms_mean: float | None


def load_probes(path: Path = PROBES_PATH) -> list[Probe]:
    """Load and validate the probes file; duplicate ids or a bad line raise `ProbeError`."""
    probes: list[Probe] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            probes.append(Probe.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ProbeError(f"{path.name} line {line_no}: {exc}") from exc
    ids = [p.id for p in probes]
    if len(ids) != len(set(ids)):
        raise ProbeError(f"{path.name}: duplicate probe ids")
    return probes


def _rate(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def summarize(timestamp: str, results: list[ProbeResult]) -> ProbeRun:
    """Compute block rate (expected-blocked) and false-block rate (expected-allowed)."""
    should_block = [r.blocked for r in results if r.expected == "blocked"]
    should_allow = [r.blocked for r in results if r.expected == "allowed"]
    times = [r.guard_ms for r in results]
    return ProbeRun(
        timestamp=timestamp,
        results=results,
        block_rate=_rate(should_block),
        false_block_rate=_rate(should_allow),
        guard_ms_mean=sum(times) / len(times) if times else None,
    )


def run_probes(probes: list[Probe], guard: PolicyGuard, timestamp: str) -> ProbeRun:
    """Classify every probe with `guard` and summarize."""
    results = []
    for probe in probes:
        trace = Trace(query_id=f"probe-{probe.id}")
        decision = guard.check(probe.question, trace)
        blocked = decision.category != "allowed"
        results.append(
            ProbeResult(
                id=probe.id,
                expected=probe.expected,
                expected_category=probe.category,
                question=probe.question,
                category=decision.category,
                reason=decision.reason,
                blocked=blocked,
                correct=blocked == (probe.expected == "blocked"),
                guard_ms=event_values(trace.events[-1])[0],
            )
        )
    return summarize(timestamp, results)


def probes_markdown(run: ProbeRun) -> str:
    """Markdown table of probe results and the two rates."""

    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.1%}"

    lines = [
        f"# Policy probes ({run.timestamp})",
        "",
        (
            f"Block rate (expected blocked): {pct(run.block_rate)}. "
            f"False-block rate (expected allowed): {pct(run.false_block_rate)}. "
            f"Guard call mean: {run.guard_ms_mean or 0:.0f} ms."
        ),
        "",
        "| id | expected | got | ok | question | reason |",
        "|---|---|---|---|---|---|",
    ]
    for r in run.results:
        lines.append(
            f"| {r.id} | {r.expected} ({r.expected_category}) | {r.category} | "
            f"{'yes' if r.correct else '**NO**'} | {r.question} | {r.reason} |"
        )
    return "\n".join(lines) + "\n"
