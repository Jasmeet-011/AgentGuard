from pathlib import Path

from agentguard.config import PROJECT_ROOT
from eval.report import METRIC_ROWS, fmt
from eval.view import (
    chart_rows,
    dev_table,
    dev_variants,
    failing_rows,
    headline_cards,
    load_runs,
    probe_summary,
    sample_size,
)

RESULTS = PROJECT_ROOT / "eval" / "results"


def _comparison_cells() -> dict[tuple[str, str, str], str]:
    """(split, variant, metric label) -> cell, parsed from latest_comparison.md."""
    cells: dict[tuple[str, str, str], str] = {}
    split, variants = "", []
    for line in (RESULTS / "latest_comparison.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            split = line[3:].strip()
        elif line.startswith("| Metric"):
            variants = [c.strip() for c in line.strip("|").split("|")][1:]
        elif line.startswith("| ") and variants and not line.startswith("| ---"):
            label, *values = [c.strip() for c in line.strip("|").split("|")]
            for variant, value in zip(variants, values, strict=True):
                cells[(split, variant, label)] = value
    return cells


def test_dev_table_matches_latest_comparison_exactly() -> None:
    runs = load_runs(RESULTS)
    cells = _comparison_cells()
    labels = {field: label for label, field, _ in METRIC_ROWS}
    checked = 0
    for run in dev_variants(runs):
        for field, kind in (
            ("retrieval_recall", "pct"),
            ("correctness", "pct"),
            ("faithfulness", "pct"),
            ("correct_refusal_rate", "pct"),
            ("false_refusal_rate", "pct"),
            ("policy_reason_rate", "pct"),
            ("latency_p50_ms", "ms"),
            ("cost_per_query_usd", "usd"),
        ):
            shown = fmt(getattr(run.aggregate, field), kind)
            assert shown == cells[("dev", run.variant, labels[field])]
            checked += 1
    assert checked == 7 * 8
    assert dev_table(dev_variants(runs))[0]["variant"] == "dense"


def test_headline_cards_match_latest_comparison_and_carry_n() -> None:
    runs = load_runs(RESULTS)
    cells = _comparison_cells()
    cards = {c.label: c for c in headline_cards(runs)}
    assert cards["Correctness"].value == cells[("test", "full", "Answer correctness")]
    assert cards["Correctness"].baseline == cells[("test", "baseline", "Answer correctness")]
    assert cards["Correctness"].n == "n=4 answerable"
    assert cards["Latency p50 (ms)"].value == cells[("test", "full", "Latency p50 (ms)")]
    assert cards["Policy block (reason = policy)"].delta == "1/1 vs 0/1"
    assert cards["Correctness"].delta == "same as baseline"
    assert cards["Correctness"].color == "off"
    assert cards["Correct refusal"].delta == "same as baseline"
    assert cards["Latency p50 (ms)"].delta == "+2868 ms"
    assert cards["Cost per query"].color == "inverse"


def test_sample_sizes_and_chart_rows() -> None:
    runs = load_runs(RESULTS)
    full = runs[("test", "full")]
    assert sample_size(full, "correct_refusal_rate") == "n=3 unanswerable"
    assert sample_size(full, "latency_p50_ms") == "n=8 questions"
    rows = chart_rows(dev_variants(runs))
    assert len(rows) == 2 * 7
    assert {r["measure"] for r in rows} == {"Correctness (%)", "Cost per query (USD)"}


def test_failing_rows_include_anything_below_one() -> None:
    runs = load_runs(RESULTS)
    failed = failing_rows(runs[("test", "full")])
    assert [r.id for r in failed] == ["q015"]
    assert any(not f.present for f in failed[0].fact_verdicts)
    assert failing_rows(runs[("dev", "full")]) == []


def test_probe_summary(tmp_path: Path) -> None:
    summary = probe_summary(RESULTS)
    assert summary is not None
    assert (summary.block_rate, summary.n_blocked_expected) == ("4/4", 4)
    assert (summary.false_block_rate, summary.n_allowed_expected) == ("0/4", 4)
    assert probe_summary(tmp_path) is None
