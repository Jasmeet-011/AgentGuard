"""Per-query tracing: record timing, token usage, and cost for each pipeline node."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from agentguard.models import Trace, TraceEvent


@contextmanager
def trace_node(trace: Trace, name: str) -> Iterator[TraceEvent]:
    """Time a node and append its event to `trace`.

    The yielded event is mutable: the node sets tokens, cost, and `detail` on it.
    The event is appended even if the node raises, so failures still show up in the trace.
    """
    event = TraceEvent(node=name, started_at=datetime.now(UTC))
    start = time.perf_counter()
    try:
        yield event
    finally:
        event.duration_ms = (time.perf_counter() - start) * 1000
        trace.events.append(event)


def event_values(event: TraceEvent) -> tuple[float, int, int, float]:
    """(ms, in tokens, out tokens, cost) of `event`; a cache hit reports the original call's.

    A cache hit records ~0 actual duration and cost, so reports that want what a query really
    takes (the CLI trace, the eval harness) read the `original_*` values from `detail` instead.
    Falls back to the actuals when a cached event carries no originals.
    """
    if not event.detail.get("cached"):
        return event.duration_ms, event.input_tokens, event.output_tokens, event.cost_usd
    return (
        event.detail.get("original_duration_ms", event.duration_ms),
        event.detail.get("original_input_tokens", event.input_tokens),
        event.detail.get("original_output_tokens", event.output_tokens),
        event.detail.get("original_cost_usd", event.cost_usd),
    )
