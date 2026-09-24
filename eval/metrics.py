"""Eval metrics. Deterministic ones are pure functions; LLM-judge scores arrive as inputs."""

import math
from collections.abc import Sequence

from agentguard.models import Answer, Chunk, Trace
from agentguard.trace import event_values
from eval.golden import ExpectedSource, GoldenEntry
from eval.records import Aggregate, QuestionResult

GENERATE_NODE = "generate"


def source_hit(chunk: Chunk, source: ExpectedSource) -> bool:
    """A chunk matches a source when firm, doc_type and item all match. Pages are ignored."""
    return (
        chunk.doc_id == source.firm
        and chunk.doc_type == source.doc_type
        and chunk.adv_item == source.item
    )


def retrieval_hit(retrieved: Sequence[Chunk], entry: GoldenEntry) -> bool:
    """Did retrieval surface the expected evidence for `entry`?

    match="any": one expected source hit suffices; "all": every expected source must be hit.
    A comparison (expected sources from more than one firm) additionally needs at least one
    retrieved chunk from every expected firm, whatever its item.
    """
    hits = [any(source_hit(c, s) for c in retrieved) for s in entry.expected_sources]
    matched = all(hits) if entry.match == "all" else any(hits)
    firms = entry.expected_firms
    if len(firms) > 1:
        retrieved_firms = {c.doc_id for c in retrieved}
        matched = matched and all(firm in retrieved_firms for firm in firms)
    return matched


def key_fact_score(present: Sequence[bool]) -> float:
    """Fraction of key facts the judge found in the answer."""
    if not present:
        raise ValueError("key_fact_score needs at least one key fact")
    return sum(present) / len(present)


def faithfulness_score(verdicts: Sequence[str]) -> float | None:
    """Fraction of sentences the judge called fully supported (partial does not count).

    None when there are no sentences to judge.
    """
    if not verdicts:
        return None
    return sum(v == "supported" for v in verdicts) / len(verdicts)


def rate(flags: Sequence[bool]) -> float | None:
    """Fraction of True flags, or None for an empty sequence."""
    return sum(flags) / len(flags) if flags else None


def mean(values: Sequence[float]) -> float | None:
    """Arithmetic mean, or None for an empty sequence."""
    return sum(values) / len(values) if values else None


def percentile(values: Sequence[float], q: float) -> float | None:
    """The q-th percentile (0-100) by linear interpolation, or None for an empty sequence."""
    if not 0 <= q <= 100:
        raise ValueError(f"percentile q must be in [0, 100], got {q}")
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def invalid_citation_counts(answer: Answer, trace: Trace) -> tuple[int, int]:
    """(invalid citations the generator emitted, total citations it emitted) for one query.

    Invalid ones were dropped before the answer was built, and are logged on the generate
    events; the kept ones are still on the answer's sentences.
    """
    invalid = sum(
        int(e.detail.get("invalid_citations_dropped", 0))
        for e in trace.events
        if e.node == GENERATE_NODE
    )
    kept = sum(len(s.citations) for s in answer.sentences)
    return invalid, invalid + kept


def latency_and_cost(trace: Trace) -> tuple[float, float]:
    """(ms, USD) a query really takes: cache hits report the original call's values."""
    values = [event_values(e) for e in trace.events]
    return sum(v[0] for v in values), sum(v[3] for v in values)


def _of_type(rows: Sequence[QuestionResult], kind: str) -> list[QuestionResult]:
    return [r for r in rows if r.type == kind]


def _present(values: Sequence[float | None]) -> list[float]:
    return [v for v in values if v is not None]


def aggregate(rows: Sequence[QuestionResult]) -> Aggregate:
    """Run-level metrics over per-question rows."""
    answerable = _of_type(rows, "answerable")
    unanswerable = _of_type(rows, "unanswerable")
    policy = _of_type(rows, "policy")
    invalid = sum(r.invalid_citations for r in rows)
    total = sum(r.total_citations for r in rows)
    latencies = [r.latency_ms for r in rows]
    return Aggregate(
        n_answerable=len(answerable),
        n_unanswerable=len(unanswerable),
        n_policy=len(policy),
        retrieval_recall=rate([bool(r.retrieval_hit) for r in answerable]),
        correctness=mean(_present([r.correctness for r in answerable])),
        faithfulness=mean(_present([r.faithfulness for r in answerable])),
        invalid_citation_rate=invalid / total if total else None,
        correct_refusal_rate=rate([r.refused for r in unanswerable]),
        false_refusal_rate=rate([r.refused for r in answerable]),
        policy_block_rate=rate([r.refused for r in policy]),
        policy_reason_rate=rate([r.refused and r.refusal_reason == "policy" for r in policy]),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        cost_per_query_usd=mean([r.cost_usd for r in rows]),
    )
