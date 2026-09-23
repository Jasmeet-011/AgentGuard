"""Item sections -> retrieval chunks of about `chunk_target_tokens`, with overlap."""

import math
import re

from pydantic import BaseModel

from agentguard.ingest.items import ITEM_TITLES
from agentguard.ingest.sections import Section
from agentguard.models import Chunk, DocType, FirmInfo

# Whitespace words x 1.3 approximates Claude/BGE subword tokens for English prose.
TOKENS_PER_WORD = 1.3
# Non-final chunks land in [MIN_FILL, MAX_FILL] x target. A sentence longer than
# MAX_UNIT x target is cut into word pieces, which keeps that bound provable.
MIN_FILL = 0.7
MAX_FILL = 1.3
MAX_UNIT = 0.5

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])")

_DOC_LABELS: dict[DocType, str] = {
    "part2a": "Form ADV Part 2A",
    "wrap_appendix1": "Wrap Fee Program Brochure",
    "part2b": "Form ADV Part 2B Brochure Supplement",
}


class Unit(BaseModel):
    """A sentence (or piece of one): the atom the chunker packs."""

    text: str
    tokens: int
    page_number: int
    paragraph_end: bool


def estimate_tokens(text: str) -> int:
    """Token estimate: whitespace-separated words x 1.3, rounded up."""
    return math.ceil(len(text.split()) * TOKENS_PER_WORD)


def _word_pieces(text: str, max_tokens: int) -> list[str]:
    words = text.split()
    size = max(1, int(max_tokens / TOKENS_PER_WORD))
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)]


def section_units(section: Section, target: int) -> list[Unit]:
    """Split a section's paragraphs into sentence units, marking paragraph ends."""
    max_unit = int(target * MAX_UNIT)
    units: list[Unit] = []
    for paragraph in section.paragraphs:
        pieces = [
            piece
            for sentence in _SENTENCE_END.split(paragraph.text)
            for piece in _word_pieces(sentence, max_unit)
        ]
        for k, piece in enumerate(pieces):
            units.append(
                Unit(
                    text=piece,
                    tokens=estimate_tokens(piece),
                    page_number=paragraph.page_number,
                    paragraph_end=k == len(pieces) - 1,
                )
            )
    return units


def _cut_index(units: list[Unit], target: int) -> int:
    """Where to end a full chunk: the last paragraph end past MIN_FILL, else all units."""
    total = 0
    best = len(units)
    for k, unit in enumerate(units, start=1):
        total += unit.tokens
        if unit.paragraph_end and total >= MIN_FILL * target:
            best = k
    return best


def _overlap(units: list[Unit], overlap: int) -> list[Unit]:
    """Trailing sentences worth <= `overlap` tokens; a word tail if the last one is longer."""
    tail: list[Unit] = []
    total = 0
    for unit in reversed(units):
        if total + unit.tokens > overlap:
            break
        tail.insert(0, unit)
        total += unit.tokens
    if tail or not units or overlap <= 0:
        return tail
    last = units[-1]
    words = last.text.split()[-max(1, int(overlap / TOKENS_PER_WORD)) :]
    text = " ".join(words)
    return [last.model_copy(update={"text": text, "tokens": estimate_tokens(text)})]


def pack_units(units: list[Unit], target: int, overlap: int) -> list[list[Unit]]:
    """Greedy packing into chunks near `target` tokens, each starting with `overlap` tokens
    carried over from the previous chunk. Prefers to end chunks at paragraph ends."""
    chunks: list[list[Unit]] = []
    current: list[Unit] = []
    fresh = 0  # units in `current` that are not overlap carried from the previous chunk
    for unit in units:
        size = sum(u.tokens for u in current)
        if size + unit.tokens > target and size >= MIN_FILL * target:
            cut = _cut_index(current, target)
            chunks.append(current[:cut])
            carried = _overlap(current[:cut], overlap)
            current = carried + current[cut:]
            fresh = len(current) - len(carried)
        current.append(unit)
        fresh += 1
    if fresh:
        chunks.append(current)
    return _merge_small_tail(chunks, target, overlap)


def _merge_small_tail(chunks: list[list[Unit]], target: int, overlap: int) -> list[list[Unit]]:
    """Fold a short final chunk into the previous one when the result stays <= MAX_FILL."""
    if len(chunks) < 2:
        return chunks
    last, prev = chunks[-1], chunks[-2]
    carried = len(_overlap(prev, overlap))
    new_part = last[carried:]
    if sum(u.tokens for u in last) < MIN_FILL * target and (
        sum(u.tokens for u in prev + new_part) <= MAX_FILL * target
    ):
        return chunks[:-2] + [prev + new_part]
    return chunks


def chunk_header(firm_name: str, section: Section) -> str:
    """Retrieval header, e.g. "Acme | Item 5: Fees and Compensation"."""
    if section.adv_item is None:
        return f"{firm_name} | {_DOC_LABELS[section.doc_type]}"
    title = ITEM_TITLES[section.doc_type][section.adv_item]
    prefix = "Wrap Fee Brochure " if section.doc_type == "wrap_appendix1" else ""
    return f"{firm_name} | {prefix}Item {section.adv_item}: {title}"


def _render(units: list[Unit]) -> str:
    """Sentences joined by spaces, paragraphs by newlines."""
    parts: list[str] = []
    for unit in units:
        parts.append(unit.text)
        parts.append("\n" if unit.paragraph_end else " ")
    return "".join(parts).strip()


def chunk_sections(
    sections: list[Section], firm: FirmInfo, target: int, overlap: int
) -> list[Chunk]:
    """Chunk every section of one brochure. IDs are `{doc_id}-p{page_start}-{k}`, where k
    counts chunks starting on that page, so they are stable across runs."""
    chunks: list[Chunk] = []
    per_page: dict[int, int] = {}
    for section in sections:
        header = chunk_header(firm.name, section)
        for units in pack_units(section_units(section, target), target, overlap):
            page_start = min(u.page_number for u in units)
            k = per_page.get(page_start, 0)
            per_page[page_start] = k + 1
            text = f"{header}\n{_render(units)}"
            chunks.append(
                Chunk(
                    chunk_id=f"{firm.slug}-p{page_start}-{k}",
                    firm_name=firm.name,
                    doc_id=firm.slug,
                    doc_type=section.doc_type,
                    adv_item=section.adv_item,
                    is_toc=section.is_toc,
                    item_title=(
                        ITEM_TITLES[section.doc_type][section.adv_item]
                        if section.adv_item is not None
                        else None
                    ),
                    page_start=page_start,
                    page_end=max(u.page_number for u in units),
                    text=text,
                    token_count=estimate_tokens(text),
                )
            )
    return chunks
