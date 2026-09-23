import logging
from pathlib import Path

import pymupdf
import pytest

from agentguard.ingest.parse import (
    _group_paragraphs,
    fix_glyphs,
    normalize_text,
    parse_pdf,
    strip_repeated_edges,
)

# Glyphs built with chr() so the test source stays ASCII-readable.
TI, TF, TT, FF, FT = chr(0x19F), chr(0x19E), chr(0x1A9), chr(0x1AF), chr(0x14C)


def test_fix_glyphs_repairs_observed_gibbs_encoding_errors() -> None:
    broken = f"informa{TI}on Por{TF}olios Alphare{TT}a A{FF}iliations a{FT}er"
    fixed, count = fix_glyphs(broken)
    assert fixed == "information Portfolios Alpharetta Affiliations after"
    assert count == 5


def test_fix_glyphs_leaves_clean_text_alone() -> None:
    assert fix_glyphs("Fees and Compensation") == ("Fees and Compensation", 0)


def test_normalize_text_handles_ligatures_and_invisible_characters() -> None:
    fi_ligature, zero_width, soft_hyphen, nbsp = chr(0xFB01), chr(0x200B), chr(0xAD), chr(0xA0)
    raw = f"  quali{fi_ligature}cations{zero_width}{nbsp}and {soft_hyphen}Connect   "
    assert normalize_text(raw) == "qualifications and Connect"


def test_paragraphs_split_on_gaps_relative_to_page_line_spacing() -> None:
    # Fisher-style layout: normal line gap is negative (boxes overlap), paragraph gap ~ +5.7.
    rows = [(0.0, 16.0, "a"), (13.6, 29.6, "b"), (35.3, 51.3, "c"), (48.9, 64.9, "d")]
    assert _group_paragraphs(rows) == [["a", "b"], ["c", "d"]]


def test_strip_repeated_edges_removes_running_footer_and_page_numbers() -> None:
    bodies = ["Advisory business", "Fee schedule", "Custody rules", "Proxy voting"]
    pages = [
        [[str(n)], [body], [f"Form ADV Part 2A | {n}"]] for n, body in enumerate(bodies, start=1)
    ]
    stripped = strip_repeated_edges(pages)
    assert stripped == [[[body]] for body in bodies]


def test_parse_pdf_logs_glyph_count_and_keeps_page_numbers(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "tiny-firm.pdf"
    doc = pymupdf.open()
    for text in ("Item 1 Cover Page", "Item 4 Advisory Business"):
        doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    with caplog.at_level(logging.INFO):
        pages = parse_pdf(path)
    assert [p.page_number for p in pages] == [1, 2]
    assert pages[1].paragraphs == [["Item 4 Advisory Business"]]
    assert pages[0].doc_id == "tiny-firm"
    assert "tiny-firm: replaced 0 mis-encoded glyphs" in caplog.text
