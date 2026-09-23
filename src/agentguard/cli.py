"""Command-line entry point: `agentguard ingest` (later: `ask`, `eval`)."""

import logging

import typer
from rich.console import Console
from rich.table import Table

from agentguard.config import Settings
from agentguard.ingest.pipeline import DocSummary, ingest_corpus, write_chunks

app = typer.Typer(help="AgentGuard: verified research over Form ADV brochures.")
console = Console()


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    """Configure logging for all commands."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


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
