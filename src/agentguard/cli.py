"""Command-line entry point: `agentguard ingest`, `search` (later: `ask`, `eval`)."""

import logging
import sys
import uuid
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentguard.config import PROJECT_ROOT, Settings
from agentguard.ingest.index import IndexSummary, build_indexes
from agentguard.ingest.pipeline import DocSummary, ingest_corpus, write_chunks
from agentguard.models import Answer, Chunk, RetrievedChunk, Trace
from agentguard.pipeline import Pipeline, run_pipeline
from agentguard.retrieval.retriever import RetrievalMode, Retriever
from agentguard.trace import event_values

app = typer.Typer(help="AgentGuard: verified research over Form ADV brochures.")
console = Console()


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    """Configure logging for all commands."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # Hugging Face model loads log every HTTP HEAD request at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _summary_table(summaries: list[DocSummary]) -> Table:
    table = Table(title="Ingestion summary")
    for column in ("Firm", "Pages", "Chunks", "Items detected", "Check"):
        table.add_column(column)
    for s in summaries:
        items = ", ".join(f"{c.doc_type} {c.detected}/{c.required}" for c in s.coverage)
        ok = all(c.ok for c in s.coverage) and bool(s.coverage)
        table.add_row(s.firm_name, str(s.pages), str(s.chunks), items, "OK" if ok else "LOW")
    return table


@app.command()
def ingest() -> None:
    """Parse and chunk every PDF in raw_dir into processed_dir/chunks.jsonl."""
    settings = Settings()
    chunks, summaries = ingest_corpus(settings)
    path = write_chunks(chunks, settings.processed_dir)
    console.print(_summary_table(summaries))
    console.print(f"Wrote {len(chunks)} chunks to {path}")
    if not all(c.ok for s in summaries for c in s.coverage):
        console.print("[red]Some brochures are below the item-detection minimum.[/red]")
        raise typer.Exit(code=1)
    _print_index_summary(build_indexes(chunks, settings))


def _print_index_summary(summary: IndexSummary) -> None:
    excluded = sum(summary.toc_excluded_per_firm.values())
    per_firm = ", ".join(f"{k} {v}" for k, v in summary.toc_excluded_per_firm.items())
    console.print(f"Indexed {summary.indexed} chunks in Qdrant and BM25.")
    console.print(f"Excluded {excluded} TOC chunks: {per_firm}")


def _fmt(score: float | None) -> str:
    return "-" if score is None else f"{score:.4f}"


def _results_table(query: str, mode: str, results: list[RetrievedChunk]) -> Table:
    table = Table(title=f"[{mode}] {query}", show_lines=True)
    for column in ("#", "chunk_id", "doc_type", "item", "pages", "dense", "bm25", "rrf", "rerank"):
        table.add_column(column)
    table.add_column("text", max_width=60)
    for rank, r in enumerate(results, start=1):
        c = r.chunk
        body = c.text.split("\n", 1)[-1]
        table.add_row(
            str(rank),
            c.chunk_id,
            c.doc_type,
            "-" if c.adv_item is None else str(c.adv_item),
            f"{c.page_start}-{c.page_end}",
            _fmt(r.dense_score),
            _fmt(r.sparse_score),
            _fmt(r.fused_score),
            _fmt(r.rerank_score),
            body[:160].replace("\n", " "),
        )
    return table


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    mode: Annotated[
        RetrievalMode | None,
        typer.Option(help="dense, hybrid, or hybrid_rerank. Default: settings.retrieval_mode."),
    ] = None,
) -> None:
    """Print the ranked chunks retrieved for QUERY, with every stage's score."""
    settings = Settings()
    mode = mode or settings.retrieval_mode
    retriever = Retriever.from_settings(settings)
    trace = Trace(query_id=uuid.uuid4().hex)
    results = retriever.retrieve(query, trace, mode=mode)
    console.print(_results_table(query, mode, results))
    event = trace.events[-1]
    console.print(f"firm filter: {event.detail['firm_filter']}  counts: {event.detail['counts']}")
    console.print(f"retrieve: {event.duration_ms:.0f} ms  stages: {event.detail['stage_ms']}")


def _page_range(start: int, end: int) -> str:
    return f"page {start}" if start == end else f"pages {start}-{end}"


def _footnote_line(n: int, chunk: Chunk) -> str:
    item = "unlabeled" if chunk.adv_item is None else f"Item {chunk.adv_item} ({chunk.item_title})"
    pages = _page_range(chunk.page_start, chunk.page_end)
    return f"[{n}] {chunk.firm_name} | {chunk.doc_type} | {item} | {pages} | {chunk.chunk_id}"


def _print_removed(answer: Answer) -> None:
    unsupported = [v for v in answer.verification if v.verdict == "unsupported"]
    if not answer.removed_sentences:
        return
    console.print("\n[red]Removed by verifier:[/red]")
    for sentence, verdict in zip(answer.removed_sentences, unsupported, strict=True):
        console.print(f"  - {sentence.text} [dim]({verdict.reason})[/dim]")


def _print_answer(answer: Answer) -> None:
    if answer.refused:
        console.print(f"[red]Refused[/red] ({answer.refusal_reason}): {answer.refusal_message}")
        _print_removed(answer)
        return
    chunks_by_id = {r.chunk.chunk_id: r.chunk for r in answer.retrieved}
    footnote_numbers: dict[str, int] = {}
    verdicts = answer.kept_verification()
    for i, sentence in enumerate(answer.sentences):
        marks = []
        for chunk_id in sentence.citations:
            footnote_numbers.setdefault(chunk_id, len(footnote_numbers) + 1)
            marks.append(str(footnote_numbers[chunk_id]))
        partial = verdicts and verdicts[i].verdict == "partial"
        tag = " [yellow](partial)[/yellow]" if partial else ""
        console.print(f"{sentence.text} [dim]^{','.join(marks)}[/dim]{tag}")
    _print_removed(answer)
    if answer.partial_note:
        console.print(
            f"\n[yellow]Not found in the retrieved passages:[/yellow] {answer.partial_note}"
        )
    if footnote_numbers:
        console.print("\nSources:")
        for chunk_id, n in footnote_numbers.items():
            console.print(_footnote_line(n, chunks_by_id[chunk_id]))


def _print_trace(trace: Trace) -> None:
    table = Table(title="Trace")
    for column in ("node", "ms", "in tok", "out tok", "cost", "cached"):
        table.add_column(column)
    original_cost_usd = 0.0
    for e in trace.events:
        ms, in_tok, out_tok, cost = event_values(e)
        original_cost_usd += cost
        table.add_row(
            e.node,
            f"{ms:.0f}",
            str(in_tok),
            str(out_tok),
            f"${cost:.4f}",
            str(e.detail.get("cached", "-")),
        )
    console.print(table)
    console.print(
        f"total: {trace.total_ms:.0f} ms, {trace.total_tokens} tokens, "
        f"${trace.total_cost_usd:.4f} actual spend (${original_cost_usd:.4f} if uncached)"
    )


@app.command()
def ask(question: Annotated[str, typer.Argument(help="Question to answer.")]) -> None:
    """Answer QUESTION with cited sentences, through the baseline retrieve+generate pipeline."""
    settings = Settings()
    answer, trace = run_pipeline(question, settings)
    _print_answer(answer)
    console.print()
    _print_trace(trace)


def _import_eval() -> None:
    """Make the repo-root `eval` package importable (it is not part of the installed package)."""
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


@app.command()
def golden() -> None:
    """Validate eval/golden.jsonl and print counts by type x split (verified / total)."""
    _import_eval()
    from eval.golden import ENTRY_TYPES, SPLITS, GoldenError, summary_counts
    from eval.run_eval import load_entries

    try:
        entries = load_entries(Settings())
    except GoldenError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    counts = summary_counts(entries)
    table = Table(title="Golden set: verified / total")
    table.add_column("type")
    for split in SPLITS:
        table.add_column(split)
    for kind in ENTRY_TYPES:
        cells = [
            f"{counts.get((kind, s), (0, 0))[1]} / {counts.get((kind, s), (0, 0))[0]}"
            for s in SPLITS
        ]
        table.add_row(kind, *cells)
    console.print(table)
    console.print(f"{len(entries)} entries, {sum(e.verified for e in entries)} verified. Valid.")


@app.command(name="eval")
def eval_command(
    variant: Annotated[
        list[str] | None, typer.Option(help="Variant to run; repeat for several. Default: all.")
    ] = None,
    split: Annotated[str, typer.Option(help="dev or test.")] = "dev",
) -> None:
    """Run the golden set (verified entries of SPLIT) through pipeline variants and record metrics."""
    _import_eval()
    from eval.report import failure_text, is_failure, run_markdown, write_comparison, write_run
    from eval.run_eval import VARIANTS, load_entries, run_variant

    settings = Settings()
    entries = load_entries(settings)
    names = variant or list(VARIANTS)
    base = Pipeline.from_settings(settings)
    for name in names:
        run = run_variant(name, split, base, settings, entries)
        json_path, _ = write_run(run, settings.results_dir)
        console.print(run_markdown(run))
        for row in (r for r in run.rows if is_failure(r)):
            console.print(f"[yellow]{failure_text(row)}[/yellow]")
        console.print(f"Wrote {json_path}")
        console.print()
    console.print(f"Wrote {write_comparison(settings.results_dir)}")


@app.command()
def probes() -> None:
    """Run the guard alone on eval/policy_probes.jsonl and record block / false-block rates."""
    _import_eval()
    from datetime import UTC, datetime

    from agentguard.agents.policy import PolicyGuard
    from agentguard.llm import LLMClient
    from eval.probes import load_probes, probes_markdown, run_probes

    settings = Settings()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    run = run_probes(load_probes(), PolicyGuard(settings, LLMClient(settings)), stamp)
    # A subfolder: `latest_comparison.md` reads every *.json directly under results_dir as a run.
    out_dir = settings.results_dir / "probes"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stamp}_policy_probes.json"
    json_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / f"{stamp}_policy_probes.md").write_text(probes_markdown(run), encoding="utf-8")
    console.print(probes_markdown(run))
    console.print(f"Wrote {json_path}")
