"""PDF -> cleaned pages: text normalization, paragraph grouping, header/footer removal."""

import logging
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pymupdf

from agentguard.models import Page

logger = logging.getLogger(__name__)

# Font-encoding errors observed in gibbs-wealth.pdf: its fonts map ligatures to unrelated
# code points, so NFKC cannot repair them. Only glyphs actually seen in our PDFs are listed.
GLYPH_FIXES: dict[str, str] = {
    "\u019f": "ti",  # seen in "information"
    "\u019e": "tf",  # seen in "Portfolios"
    "\u01a9": "tt",  # seen in "Alpharetta"
    "\u01af": "ff",  # seen in "Affiliations"
    "\u014c": "ft",  # seen in "after"
    "\uf0b7": "\u2022",  # private-use Symbol-font bullet -> standard bullet
}
_GLYPH_RE = re.compile("|".join(GLYPH_FIXES))

# Invisible or layout-only characters: zero-width space, soft hyphen, BOM, Unicode line and
# paragraph separators, and the Unicode hyphen (NFKC leaves it alone).
_CHAR_FIXES = str.maketrans(
    {"\u200b": "", "\u00ad": "", "\ufeff": "", "\u2028": " ", "\u2029": " ", "\u2010": "-"}
)

# A row whose top overlaps the previous row by more than this fraction of its height is on
# the same visual row (e.g. "C." and its heading). A gap larger than the page's median row
# gap plus this fraction of line height starts a new paragraph.
SAME_ROW_OVERLAP = 0.5
PARAGRAPH_GAP = 0.3
# Lines within this many lines of the top/bottom of a page are header/footer candidates;
# they are stripped if (digits ignored) they repeat on more than this share of pages.
EDGE_LINES = 3
REPEAT_SHARE = 0.5


def fix_glyphs(text: str) -> tuple[str, int]:
    """Replace known mis-encoded glyphs. Returns (fixed text, number of replacements)."""
    return _GLYPH_RE.subn(lambda m: GLYPH_FIXES[m.group()], text)


def normalize_text(text: str) -> str:
    """NFKC (standard ligatures, NBSP), drop invisible characters, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_CHAR_FIXES)
    return re.sub(r"\s+", " ", text).strip()


def _page_rows(page: pymupdf.Page) -> list[tuple[float, float, str]]:
    """Visual rows (y0, y1, raw text) in reading order, merging spans on the same row."""
    rows: list[tuple[float, float, str]] = []
    for block in page.get_text("dict", sort=True)["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"])
            if not text.strip():
                continue
            y0, y1 = line["bbox"][1], line["bbox"][3]
            if rows and rows[-1][1] - y0 > SAME_ROW_OVERLAP * (y1 - y0):
                prev_y0, prev_y1, prev_text = rows[-1]
                rows[-1] = (prev_y0, max(prev_y1, y1), f"{prev_text} {text}")
            else:
                rows.append((y0, y1, text))
    return rows


def _group_paragraphs(rows: list[tuple[float, float, str]]) -> list[list[str]]:
    """Split rows into paragraphs where the gap exceeds the page's usual line gap.

    Line boxes often overlap (negative gaps), so the threshold is relative to the page's
    median gap between consecutive rows, not to zero.
    """
    gaps = [rows[i][0] - rows[i - 1][1] for i in range(1, len(rows))]
    usual_gap = statistics.median(gaps) if gaps else 0.0
    paragraphs: list[list[str]] = []
    for i, (y0, y1, text) in enumerate(rows):
        if i == 0 or gaps[i - 1] > usual_gap + PARAGRAPH_GAP * (y1 - y0):
            paragraphs.append([])
        paragraphs[-1].append(text)
    return paragraphs


def _clean_paragraphs(paragraphs: list[list[str]]) -> tuple[list[list[str]], int]:
    fixed_count = 0
    cleaned: list[list[str]] = []
    for paragraph in paragraphs:
        lines: list[str] = []
        for raw in paragraph:
            text, n = fix_glyphs(raw)
            fixed_count += n
            if line := normalize_text(text):
                lines.append(line)
        if lines:
            cleaned.append(lines)
    return cleaned, fixed_count


def _edge_key(line: str) -> str:
    return re.sub(r"\d+", "#", line.lower())


def _edge_positions(paragraphs: list[list[str]]) -> list[tuple[int, int]]:
    """(paragraph, line) indices of the first and last EDGE_LINES lines of a page."""
    flat = [(p, i) for p, para in enumerate(paragraphs) for i in range(len(para))]
    return sorted(set(flat[:EDGE_LINES] + flat[-EDGE_LINES:]))


def strip_repeated_edges(pages: list[list[list[str]]]) -> list[list[list[str]]]:
    """Drop header/footer lines: top/bottom lines repeating (digits ignored) on >50% of pages."""
    counts: Counter[str] = Counter()
    for paragraphs in pages:
        counts.update({_edge_key(paragraphs[p][i]) for p, i in _edge_positions(paragraphs)})
    repeated = {key for key, n in counts.items() if n > REPEAT_SHARE * len(pages)}
    result: list[list[list[str]]] = []
    for paragraphs in pages:
        drop = {
            (p, i)
            for p, i in _edge_positions(paragraphs)
            if _edge_key(paragraphs[p][i]) in repeated
        }
        kept = [
            [line for i, line in enumerate(para) if (p, i) not in drop]
            for p, para in enumerate(paragraphs)
        ]
        result.append([para for para in kept if para])
    return result


def parse_pdf(path: Path) -> list[Page]:
    """Parse a brochure PDF into cleaned pages (1-based page numbers, doc_id = file stem)."""
    doc: Any = pymupdf.open(path)
    raw_pages: list[list[list[str]]] = []
    glyph_fixes = 0
    for page in doc:
        paragraphs, n = _clean_paragraphs(_group_paragraphs(_page_rows(page)))
        raw_pages.append(paragraphs)
        glyph_fixes += n
    logger.info("%s: replaced %d mis-encoded glyphs", path.stem, glyph_fixes)
    return [
        Page(doc_id=path.stem, page_number=number, paragraphs=paragraphs)
        for number, paragraphs in enumerate(strip_repeated_edges(raw_pages), start=1)
    ]
