"""Pure formatting helpers behind `agentguard ask`'s output."""

from datetime import UTC, datetime

from agentguard.cli import _page_range, _trace_row_values
from agentguard.models import TraceEvent


def test_page_range_collapses_equal_start_and_end() -> None:
    assert _page_range(13, 13) == "page 13"


def test_page_range_shows_a_dash_when_different() -> None:
    assert _page_range(13, 14) == "pages 13-14"


def _event(**detail: object) -> TraceEvent:
    return TraceEvent(
        node="generate",
        started_at=datetime.now(UTC),
        duration_ms=5.0,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        detail=detail,
    )


def test_trace_row_values_uses_actual_numbers_when_not_cached() -> None:
    event = TraceEvent(
        node="generate",
        started_at=datetime.now(UTC),
        duration_ms=2500.0,
        input_tokens=900,
        output_tokens=120,
        cost_usd=0.0018,
        detail={"cached": False},
    )
    assert _trace_row_values(event) == (2500.0, 900, 120, 0.0018)


def test_trace_row_values_uses_original_numbers_when_cached() -> None:
    event = _event(
        cached=True,
        original_duration_ms=2500.0,
        original_input_tokens=900,
        original_output_tokens=120,
        original_cost_usd=0.0139,
    )
    assert _trace_row_values(event) == (2500.0, 900, 120, 0.0139)


def test_trace_row_values_falls_back_to_actual_if_originals_missing() -> None:
    event = _event(cached=True)
    assert _trace_row_values(event) == (5.0, 0, 0, 0.0)
