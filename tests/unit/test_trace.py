import time

import pytest

from agentguard.models import Trace
from agentguard.trace import trace_node


def test_trace_node_records_duration_and_attached_usage() -> None:
    trace = Trace(query_id="q1")
    with trace_node(trace, "retrieve") as event:
        time.sleep(0.02)
        event.input_tokens = 7
        event.detail["hits"] = 3
    assert len(trace.events) == 1
    recorded = trace.events[0]
    assert recorded.node == "retrieve"
    assert recorded.duration_ms >= 15
    assert recorded.input_tokens == 7
    assert recorded.detail == {"hits": 3}


def test_trace_node_records_event_even_when_node_raises() -> None:
    trace = Trace(query_id="q1")
    with pytest.raises(RuntimeError), trace_node(trace, "generate"):
        raise RuntimeError("boom")
    assert [e.node for e in trace.events] == ["generate"]
    assert trace.events[0].duration_ms >= 0
