"""Write eval results: per-run JSON + markdown, the cross-variant comparison, and failures."""

from pathlib import Path

from eval.records import Aggregate, QuestionResult, RunResult

# (label, Aggregate field, format) in the order shown in every table.
METRIC_ROWS: list[tuple[str, str, str]] = [
    ("Retrieval recall@k", "retrieval_recall", "pct"),
    ("Answer correctness", "correctness", "pct"),
    ("Faithfulness", "faithfulness", "pct"),
    ("Invalid citation rate", "invalid_citation_rate", "pct"),
    ("Correct refusal rate (unanswerable)", "correct_refusal_rate", "pct"),
    ("False refusal rate (answerable)", "false_refusal_rate", "pct"),
    ("Policy block rate (any refusal)", "policy_block_rate", "pct"),
    ("Policy block rate (reason = policy)", "policy_reason_rate", "pct"),
    ("Latency p50 (ms)", "latency_p50_ms", "ms"),
    ("Latency p95 (ms)", "latency_p95_ms", "ms"),
    ("Cost per query (USD, pipeline only)", "cost_per_query_usd", "usd"),
    ("Eval cost per question (USD, judge)", "eval_cost_per_question_usd", "usd"),
]
PRELIMINARY_NOTE = (
    "PRELIMINARY: the golden set is incomplete (fewer verified entries than the minimum), "
    "so these numbers are not headline numbers."
)


def fmt(value: float | None, kind: str) -> str:
    """Format a metric value; None (no applicable questions) is "n/a"."""
    if value is None:
        return "n/a"
    return {"pct": f"{value:.1%}", "ms": f"{value:.0f}", "usd": f"${value:.4f}"}[kind]


def _counts_line(a: Aggregate) -> str:
    return f"{a.n_answerable} answerable, {a.n_unanswerable} unanswerable, {a.n_policy} policy"


def run_stem(run: RunResult) -> str:
    """File stem `{timestamp}_{variant}_{split}` shared by a run's JSON and markdown."""
    return f"{run.timestamp}_{run.variant}_{run.split}"


def run_markdown(run: RunResult) -> str:
    """Markdown summary of one run."""
    lines = [f"# {run.variant} on {run.split} ({run.timestamp})", ""]
    if run.preliminary:
        lines += [f"**{PRELIMINARY_NOTE}**", ""]
    lines += [
        (
            f"Questions: {_counts_line(run.aggregate)} ({run.verified_in_file} verified in "
            f"file, {run.unverified_skipped} unverified skipped). Retrieval k = {run.top_k}."
        ),
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for label, field, kind in METRIC_ROWS:
        lines.append(f"| {label} | {fmt(getattr(run.aggregate, field), kind)} |")
    return "\n".join(lines) + "\n"


def write_run(run: RunResult, results_dir: Path) -> tuple[Path, Path]:
    """Write `{stem}.json` and `{stem}.md` into `results_dir`."""
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / f"{run_stem(run)}.json"
    md_path = results_dir / f"{run_stem(run)}.md"
    json_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(run_markdown(run), encoding="utf-8")
    return json_path, md_path


def latest_runs(results_dir: Path) -> dict[tuple[str, str], RunResult]:
    """The most recent run for each (split, variant) found in `results_dir`."""
    latest: dict[tuple[str, str], RunResult] = {}
    for path in sorted(results_dir.glob("*.json")):
        run = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        latest[(run.split, run.variant)] = run  # sorted by name = by timestamp; last wins
    return latest


def comparison_markdown(runs: dict[tuple[str, str], RunResult]) -> str:
    """One table per split, variants side by side, from each variant's latest run."""
    lines = ["# Latest comparison", ""]
    for split in ("dev", "test"):
        selected = [run for (s, _), run in sorted(runs.items()) if s == split]
        if not selected:
            continue
        lines += [f"## {split}", ""]
        if any(run.preliminary for run in selected):
            lines += [f"**{PRELIMINARY_NOTE}**", ""]
        lines.append("| Metric | " + " | ".join(run.variant for run in selected) + " |")
        lines.append("|---|" + "---|" * len(selected))
        lines.append(
            "| Questions | " + " | ".join(_counts_line(r.aggregate) for r in selected) + " |"
        )
        for label, field, kind in METRIC_ROWS:
            cells = " | ".join(fmt(getattr(r.aggregate, field), kind) for r in selected)
            lines.append(f"| {label} | {cells} |")
        lines.append("")
    return "\n".join(lines)


def write_comparison(results_dir: Path) -> Path:
    """Regenerate `latest_comparison.md` from the latest run of every variant and split."""
    path = results_dir / "latest_comparison.md"
    path.write_text(comparison_markdown(latest_runs(results_dir)), encoding="utf-8")
    return path


def is_failure(row: QuestionResult) -> bool:
    """An answerable question with correctness < 0.5 or faithfulness < 1.0."""
    if row.type != "answerable":
        return False
    return (row.correctness or 0.0) < 0.5 or (
        row.faithfulness is not None and row.faithfulness < 1.0
    )


def failure_text(row: QuestionResult) -> str:
    """Question, answer, and the judge's reasons, for debugging one failed row."""
    correctness = "n/a" if row.correctness is None else f"{row.correctness:.2f}"
    faithfulness = "n/a" if row.faithfulness is None else f"{row.faithfulness:.2f}"
    lines = [
        f"[{row.id}] {row.question}",
        (
            f"  correctness={correctness} faithfulness={faithfulness} "
            f"retrieval_hit={row.retrieval_hit} refused={row.refused}"
        ),
        f"  answer: {row.answer_text or '(refused)'}",
    ]
    for f in row.fact_verdicts:
        lines.append(f"  fact {'present' if f.present else 'MISSING'} {f.key_fact!r}: {f.reason}")
    for v in row.sentence_verdicts:
        if v.verdict != "supported":
            lines.append(f"  sentence {v.verdict} {v.sentence!r}: {v.reason}")
    return "\n".join(lines)
