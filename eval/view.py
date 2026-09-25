"""View models for the Evals tab: read finished eval results and shape them for display.

Nothing here runs or recomputes an eval. Numbers come from `Aggregate` fields (formatted with
`report.fmt`, the same formatter as `latest_comparison.md`), so the tab and that file agree.
"""

from pathlib import Path

from pydantic import BaseModel

from eval.records import Aggregate, ProbeRun, QuestionResult, RunResult
from eval.report import fmt, latest_runs

DEV_ORDER: tuple[str, ...] = (
    "dense",
    "hybrid",
    "baseline",
    "+verifier",
    "+decompose",
    "+verifier+decompose",
    "full",
)

# (label, Aggregate field, format, which side is better: "high", "low", or None for neutral)
# Used by both the headline cards and the dev table.
TABLE_METRICS: tuple[tuple[str, str, str, str], ...] = (
    ("Retrieval recall@k", "retrieval_recall", "pct", "high"),
    ("Correctness", "correctness", "pct", "high"),
    ("Faithfulness", "faithfulness", "pct", "high"),
    ("Correct refusal", "correct_refusal_rate", "pct", "high"),
    ("False refusal", "false_refusal_rate", "pct", "low"),
    ("Policy block (reason = policy)", "policy_reason_rate", "pct", "high"),
    ("Latency p50 (ms)", "latency_p50_ms", "ms", "low"),
    ("Cost per query", "cost_per_query_usd", "usd", "low"),
)


class Card(BaseModel):
    """One headline metric: the `full` value, its delta vs baseline, and the sample size."""

    label: str
    n: str
    value: str
    baseline: str
    delta: str
    color: str  # streamlit delta_color: "normal", "inverse" or "off"


class ProbeSummary(BaseModel):
    """Block and false-block rate on the policy probes, with their denominators."""

    block_rate: str  # a count ("4/4") when n is small, else a percentage
    n_blocked_expected: int
    false_block_rate: str
    n_allowed_expected: int
    timestamp: str


def load_runs(results_dir: Path) -> dict[tuple[str, str], RunResult]:
    """Latest run per (split, variant) from `results_dir`."""
    return latest_runs(results_dir)


# Below this many questions, a percentage or a percentage-point delta overstates precision.
SMALL_N = 5


def sample_n(run: RunResult, field: str) -> int:
    """The number of questions behind an Aggregate field."""
    a = run.aggregate
    return {
        "retrieval_recall": a.n_answerable,
        "correctness": a.n_answerable,
        "faithfulness": sum(r.faithfulness is not None for r in run.rows),
        "correct_refusal_rate": a.n_unanswerable,
        "false_refusal_rate": a.n_answerable,
        "policy_reason_rate": a.n_policy,
    }.get(field, len(run.rows))


def sample_size(run: RunResult, field: str) -> str:
    """The n behind an Aggregate field, e.g. "n=4 answerable"."""
    what = {
        "retrieval_recall": "answerable",
        "correctness": "answerable",
        "faithfulness": "answerable, not refused",
        "correct_refusal_rate": "unanswerable",
        "false_refusal_rate": "answerable",
        "policy_reason_rate": "policy",
    }.get(field, "questions")
    return f"n={sample_n(run, field)} {what}"


def count_text(rate: float | None, n: int) -> str:
    """A rate as a count out of n, e.g. "1/1". Scores that average partial credit can be fractional."""
    if rate is None:
        return "n/a"
    return f"{round(rate * n, 2):g}/{n}"


def _delta(
    full: float | None, base: float | None, kind: str, better: str, n: int
) -> tuple[str, str]:
    """Delta text and streamlit colour for `full` vs `base`; counts instead of points if n is small."""
    if full is None or base is None:
        return "n/a", "off"
    diff = full - base
    if kind == "pct" and n < SMALL_N:
        text = f"{count_text(full, n)} vs {count_text(base, n)}"
    elif kind == "pct":
        text = f"{diff * 100:+.1f} pts"
    elif kind == "ms":
        text = f"{diff:+.0f} ms"
    else:
        text = f"{diff:+.4f} USD"
    if round(diff, 6) == 0:
        return text, "off"
    return text, "normal" if better == "high" else "inverse"


def headline_cards(runs: dict[tuple[str, str], RunResult]) -> list[Card]:
    """Test-split cards: `full` against `baseline`. Empty if either run is missing."""
    base, full = runs.get(("test", "baseline")), runs.get(("test", "full"))
    if base is None or full is None:
        return []
    cards = []
    for label, field, kind, better in TABLE_METRICS:
        f, b = getattr(full.aggregate, field), getattr(base.aggregate, field)
        delta, color = _delta(f, b, kind, better, sample_n(full, field))
        cards.append(
            Card(
                label=label,
                n=sample_size(full, field),
                value=fmt(f, kind),
                baseline=fmt(b, kind),
                delta=delta,
                color=color,
            )
        )
    return cards


def dev_variants(runs: dict[tuple[str, str], RunResult]) -> list[RunResult]:
    """Dev runs in the fixed display order; variants with no dev run are left out."""
    return [runs[("dev", v)] for v in DEV_ORDER if ("dev", v) in runs]


def dev_table(variants: list[RunResult]) -> list[dict[str, str]]:
    """One row per variant, one column per metric, values as formatted in latest_comparison.md."""
    if not variants:
        return []
    ns = variants[0]
    rows = []
    for run in variants:
        row = {"variant": run.variant}
        for label, field, kind, _ in TABLE_METRICS:
            row[f"{label} ({sample_size(ns, field)})"] = fmt(getattr(run.aggregate, field), kind)
        rows.append(row)
    return rows


def chart_rows(variants: list[RunResult]) -> list[dict[str, object]]:
    """Long-format rows for the correctness and cost bars: one per variant and measure."""
    rows: list[dict[str, object]] = []
    for run in variants:
        a: Aggregate = run.aggregate
        if a.correctness is not None:
            rows.append(
                {
                    "variant": run.variant,
                    "measure": "Correctness (%)",
                    "value": a.correctness * 100,
                    "label": fmt(a.correctness, "pct"),
                }
            )
        if a.cost_per_query_usd is not None:
            rows.append(
                {
                    "variant": run.variant,
                    "measure": "Cost per query (USD)",
                    "value": a.cost_per_query_usd,
                    "label": fmt(a.cost_per_query_usd, "usd"),
                }
            )
    return rows


def _rate_text(rate: float | None, n: int) -> str:
    return count_text(rate, n) if n < SMALL_N else fmt(rate, "pct")


def probe_summary(results_dir: Path) -> ProbeSummary | None:
    """The latest policy-probe run in `results_dir/probes`, or None if there is none."""
    files = sorted((results_dir / "probes").glob("*.json"))
    if not files:
        return None
    run = ProbeRun.model_validate_json(files[-1].read_text(encoding="utf-8"))
    blocked = sum(r.expected == "blocked" for r in run.results)
    allowed = sum(r.expected == "allowed" for r in run.results)
    return ProbeSummary(
        block_rate=_rate_text(run.block_rate, blocked),
        n_blocked_expected=blocked,
        false_block_rate=_rate_text(run.false_block_rate, allowed),
        n_allowed_expected=allowed,
        timestamp=run.timestamp,
    )


def failing_rows(run: RunResult) -> list[QuestionResult]:
    """Answerable questions with correctness or faithfulness below 1.0 (None = not applicable)."""
    out = []
    for row in run.rows:
        if row.type != "answerable":
            continue
        below = (row.correctness is not None and row.correctness < 1.0) or (
            row.faithfulness is not None and row.faithfulness < 1.0
        )
        if below:
            out.append(row)
    return out
