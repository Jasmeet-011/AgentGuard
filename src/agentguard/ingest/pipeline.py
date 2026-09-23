"""Run parse + section split + chunk over every brochure and write chunks.jsonl."""

import logging
from pathlib import Path

from pydantic import BaseModel

from agentguard.config import Settings
from agentguard.ingest.chunk import chunk_sections
from agentguard.ingest.firms import firm_for_pdf, load_firms
from agentguard.ingest.items import REQUIRED_ITEMS
from agentguard.ingest.parse import parse_pdf
from agentguard.ingest.sections import split_sections
from agentguard.models import Chunk, DocType

logger = logging.getLogger(__name__)

CHUNKS_FILENAME = "chunks.jsonl"
# M2 acceptance: minimum required items detected per brochure type.
MIN_ITEMS_DETECTED: dict[DocType, int] = {"part2a": 12, "wrap_appendix1": 7}


class ItemCoverage(BaseModel):
    """How many of a brochure type's required items were detected in one PDF."""

    doc_type: DocType
    detected: int
    required: int
    minimum: int

    @property
    def ok(self) -> bool:
        return self.detected >= self.minimum


class DocSummary(BaseModel):
    """Ingestion result for one PDF, printed by `agentguard ingest`."""

    firm_name: str
    doc_id: str
    pages: int
    chunks: int
    coverage: list[ItemCoverage]


def item_coverage(chunks: list[Chunk]) -> list[ItemCoverage]:
    """Detected required items per labeled brochure type present in `chunks`."""
    coverage: list[ItemCoverage] = []
    for doc_type, minimum in MIN_ITEMS_DETECTED.items():
        typed = [c for c in chunks if c.doc_type == doc_type]
        if not typed:
            continue
        detected = {c.adv_item for c in typed} & set(REQUIRED_ITEMS[doc_type])
        coverage.append(
            ItemCoverage(
                doc_type=doc_type,
                detected=len(detected),
                required=len(REQUIRED_ITEMS[doc_type]),
                minimum=minimum,
            )
        )
    return coverage


def ingest_corpus(settings: Settings) -> tuple[list[Chunk], list[DocSummary]]:
    """Parse and chunk every PDF in `raw_dir`, in filename order."""
    pdfs = sorted(settings.raw_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs in {settings.raw_dir}")
    firms = load_firms(settings.raw_dir)
    all_chunks: list[Chunk] = []
    summaries: list[DocSummary] = []
    for pdf in pdfs:
        firm = firm_for_pdf(pdf, firms)
        pages = parse_pdf(pdf)
        chunks = chunk_sections(
            split_sections(pages, firm),
            firm,
            settings.chunk_target_tokens,
            settings.chunk_overlap_tokens,
        )
        logger.info("%s: %d pages -> %d chunks", pdf.stem, len(pages), len(chunks))
        all_chunks.extend(chunks)
        summaries.append(
            DocSummary(
                firm_name=firm.name,
                doc_id=firm.slug,
                pages=len(pages),
                chunks=len(chunks),
                coverage=item_coverage(chunks),
            )
        )
    return all_chunks, summaries


def write_chunks(chunks: list[Chunk], processed_dir: Path) -> Path:
    """Write one JSON object per line to `{processed_dir}/chunks.jsonl`."""
    processed_dir.mkdir(parents=True, exist_ok=True)
    path = processed_dir / CHUNKS_FILENAME
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk.model_dump_json() + "\n")
    return path
