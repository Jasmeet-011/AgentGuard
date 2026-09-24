"""Command-line entry point: `agentguard ingest`, `search` (later: `ask`, `eval`)."""

import logging
import uuid
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentguard.config import Settings
from agentguard.ingest.index import IndexSummary, build_indexes
from agentguard.ingest.pipeline import DocSummary, ingest_corpus, write_chunks
from agentguard.models import Answer, Chunk, RetrievedChunk, Trace, TraceEvent
from agentguard.pipeline import run_pipeline
from agentguard.retrieval.retriever import RetrievalMode, Retriever

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


def _print_answer(answer: Answer) -> None:
    if answer.refused:
        console.print(f"[red]Refused[/red] ({answer.refusal_reason}): {answer.refusal_message}")
        return
    chunks_by_id = {r.chunk.chunk_id: r.chunk for r in answer.retrieved}
    footnote_numbers: dict[str, int] = {}
    for sentence in answer.sentences:
        marks = []
        for chunk_id in sentence.citations:
            footnote_numbers.setdefault(chunk_id, len(footnote_numbers) + 1)
            marks.append(str(footnote_numbers[chunk_id]))
        console.print(f"{sentence.text} [dim]^{','.join(marks)}[/dim]")
    if answer.partial_note:
        console.print(f"\n[yellow]Not covered by the documents:[/yellow] {answer.partial_note}")
    if footnote_numbers:
        console.print("\nSources:")
        for chunk_id, n in footnote_numbers.items():
            console.print(_footnote_line(n, chunks_by_id[chunk_id]))


def _trace_row_values(e: TraceEvent) -> tuple[float, int, int, float]:
    """(ms, in tokens, out tokens, cost) to display: a cache hit shows the original call's."""
    if not e.detail.get("cached"):
        return e.duration_ms, e.input_tokens, e.output_tokens, e.cost_usd
    return (
        e.detail.get("original_duration_ms", e.duration_ms),
        e.detail.get("original_input_tokens", e.input_tokens),
        e.detail.get("original_output_tokens", e.output_tokens),
        e.detail.get("original_cost_usd", e.cost_usd),
    )


def _print_trace(trace: Trace) -> None:
    table = Table(title="Trace")
    for column in ("node", "ms", "in tok", "out tok", "cost", "cached"):
        table.add_column(column)
    original_cost_usd = 0.0
    for e in trace.events:
        ms, in_tok, out_tok, cost = _trace_row_values(e)
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
