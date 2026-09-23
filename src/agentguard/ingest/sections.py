"""Cleaned pages -> item sections: split by brochure type, then by ADV item heading."""

from itertools import groupby

from pydantic import BaseModel

from agentguard.ingest.items import (
    TOC_ITEM,
    is_part2b_cover,
    is_toc_page,
    match_item_heading,
    match_title_heading,
)
from agentguard.models import DocType, FirmInfo, Page

# A document that has this many distinct explicit "Item N" headings uses them consistently,
# so bare-title matches in it are subheadings ("Client Referrals - Schwab"), not items.
MIN_EXPLICIT_ITEMS = 6


class Paragraph(BaseModel):
    """One paragraph of body text and the page it is on."""

    page_number: int
    text: str


class Section(BaseModel):
    """A run of paragraphs that share a brochure type and ADV item (None = unlabeled)."""

    doc_type: DocType
    adv_item: int | None
    paragraphs: list[Paragraph]
    is_toc: bool = False  # started by a table-of-contents page (labeled Item 3)


class _Candidate(BaseModel):
    page_number: int
    line_index: int  # index into the page's flattened lines
    item: int
    explicit: bool
    toc: bool = False


def _lines(page: Page) -> list[str]:
    return [line for paragraph in page.paragraphs for line in paragraph]


def assign_doc_types(pages: list[Page], firm: FirmInfo) -> list[DocType]:
    """Brochure type of each page: Part 2A (or wrap appendix), then Part 2B once it starts.

    Part 2B starts at the first non-TOC page with a "Form ADV Part 2B" cover line. TOC pages
    are excluded because tables of contents list the Part 2B supplement too.
    """
    types: list[DocType] = []
    for page in pages:
        doc_type: DocType = firm.doc_type
        if firm.wrap_appendix1_from_page and page.page_number >= firm.wrap_appendix1_from_page:
            doc_type = "wrap_appendix1"
        lines = _lines(page)
        if (types and types[-1] == "part2b") or (
            is_part2b_cover(lines) and not is_toc_page(lines, doc_type)
        ):
            doc_type = "part2b"
        types.append(doc_type)
    return types


def _page_candidates(page: Page, doc_type: DocType) -> list[_Candidate]:
    lines = _lines(page)
    found: list[_Candidate] = []
    for i, line in enumerate(lines):
        next_line = lines[i + 1] if i + 1 < len(lines) else None
        if (item := match_item_heading(line, next_line, doc_type)) is not None:
            found.append(
                _Candidate(page_number=page.page_number, line_index=i, item=item, explicit=True)
            )
        elif (item := match_title_heading(line, doc_type)) is not None:
            found.append(
                _Candidate(page_number=page.page_number, line_index=i, item=item, explicit=False)
            )
    return found


def find_candidates(pages: list[Page], doc_type: DocType) -> list[_Candidate]:
    """Heading candidates in reading order. The first page of each TOC run counts as Item 3."""
    candidates: list[_Candidate] = []
    previous_was_toc = False
    for page in pages:
        toc = is_toc_page(_lines(page), doc_type)
        if toc and not previous_was_toc:
            candidates.append(
                _Candidate(
                    page_number=page.page_number,
                    line_index=0,
                    item=TOC_ITEM,
                    explicit=True,
                    toc=True,
                )
            )
        elif not toc:
            candidates.extend(_page_candidates(page, doc_type))
        previous_was_toc = toc
    explicit_items = {c.item for c in candidates if c.explicit}
    if len(explicit_items) >= MIN_EXPLICIT_ITEMS:
        candidates = [c for c in candidates if c.explicit]
    return candidates


def select_boundaries(candidates: list[_Candidate]) -> list[_Candidate]:
    """Longest run of candidates with strictly increasing item numbers.

    Brochures present items in order, so this drops cross-references and Material Changes
    summaries that name items out of order. Ties go to the earliest candidate.
    """
    if not candidates:
        return []
    best = [1] * len(candidates)
    prev: list[int | None] = [None] * len(candidates)
    for i, cand in enumerate(candidates):
        for j in range(i):
            if candidates[j].item < cand.item and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    end: int | None = best.index(max(best))
    chain: list[_Candidate] = []
    while end is not None:
        chain.append(candidates[end])
        end = prev[end]
    return chain[::-1]


def _split_segment(pages: list[Page], doc_type: DocType) -> list[Section]:
    starts = {
        (c.page_number, c.line_index): c
        for c in select_boundaries(find_candidates(pages, doc_type))
    }
    sections = [Section(doc_type=doc_type, adv_item=None, paragraphs=[])]
    for page in pages:
        line_index = 0
        for paragraph in page.paragraphs:
            current: list[str] = []
            for line in paragraph:
                start = starts.get((page.page_number, line_index))
                if start is not None:
                    _flush(sections[-1], page.page_number, current)
                    sections.append(
                        Section(
                            doc_type=doc_type,
                            adv_item=start.item,
                            paragraphs=[],
                            is_toc=start.toc,
                        )
                    )
                    current = []
                current.append(line)
                line_index += 1
            _flush(sections[-1], page.page_number, current)
    return [s for s in sections if s.paragraphs]


def _flush(section: Section, page_number: int, lines: list[str]) -> None:
    if lines:
        section.paragraphs.append(Paragraph(page_number=page_number, text=" ".join(lines)))


def split_sections(pages: list[Page], firm: FirmInfo) -> list[Section]:
    """Split a parsed brochure into item sections, per brochure type within the PDF.

    Part 2B supplements are kept as unlabeled sections (their Items 1-7 are about individual
    advisers, not the firm's ADV items).
    """
    sections: list[Section] = []
    typed = zip(assign_doc_types(pages, firm), pages, strict=True)
    for doc_type, group in groupby(typed, key=lambda pair: pair[0]):
        segment = [page for _, page in group]
        if doc_type == "part2b":
            sections.extend(_split_segment_unlabeled(segment))
        else:
            sections.extend(_split_segment(segment, doc_type))
    return sections


def _split_segment_unlabeled(pages: list[Page]) -> list[Section]:
    paragraphs = [
        Paragraph(page_number=page.page_number, text=" ".join(lines))
        for page in pages
        for lines in page.paragraphs
    ]
    return [Section(doc_type="part2b", adv_item=None, paragraphs=paragraphs)] if paragraphs else []
