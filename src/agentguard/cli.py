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
from agentguard.models import RetrievedChunk, Trace
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
