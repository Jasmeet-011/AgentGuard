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
