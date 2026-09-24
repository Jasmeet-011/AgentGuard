"""Regression checks over the real brochures in data/raw (local files, no network)."""

import pytest

from agentguard.config import Settings
from agentguard.ingest.pipeline import DocSummary, ingest_corpus
from agentguard.models import Chunk


@pytest.fixture(scope="module")
def corpus() -> tuple[list[Chunk], list[DocSummary]]:
    return ingest_corpus(Settings(anthropic_api_key="sk-test"))


def test_every_brochure_meets_item_detection_minimum(
    corpus: tuple[list[Chunk], list[DocSummary]],
) -> None:
    _, summaries = corpus
    low = [(s.doc_id, c.doc_type, c.detected) for s in summaries for c in s.coverage if not c.ok]
    assert not low
    betterment = next(s for s in summaries if s.doc_id == "betterment")
    assert {c.doc_type for c in betterment.coverage} == {"part2a", "wrap_appendix1"}


def test_chunk_ids_unique_and_stable_across_runs(
    corpus: tuple[list[Chunk], list[DocSummary]],
) -> None:
    chunks, _ = corpus
    ids = [c.chunk_id for c in chunks]
    assert len(set(ids)) == len(ids)
    rerun, _ = ingest_corpus(Settings(anthropic_api_key="sk-test"))
    assert [c.chunk_id for c in rerun] == ids
    assert [c.text for c in rerun] == [c.text for c in chunks]


def test_known_sections_land_in_the_right_item(
    corpus: tuple[list[Chunk], list[DocSummary]],
) -> None:
    chunks, _ = corpus

    def item_of(doc_id: str, phrase: str) -> set[int | None]:
        return {c.adv_item for c in chunks if c.doc_id == doc_id and phrase in c.text}

    assert item_of("fisher-investments", "First $1 million") == {5}
    assert item_of("vanguard-personal-advisor", "$19.5 million penalty") == {9}
    assert item_of("creative-planning", "prohibited client testimonials") >= {9}
    assert 9 in item_of("gibbs-wealth", "Third Judicial District Court")
    # Vanguard's appended "Investment risks" pages are not Item 19 (M3 regression).
    assert item_of("vanguard-personal-advisor", "Cybersecurity risks") == {None}
    assert item_of("vanguard-personal-advisor", "Ownership limitations") == {None}
    assert item_of("vanguard-personal-advisor", "VAI is a federally registered") == {19}


def test_gibbs_glyphs_repaired(corpus: tuple[list[Chunk], list[DocSummary]]) -> None:
    chunks, _ = corpus
    gibbs = " ".join(c.text for c in chunks if c.doc_id == "gibbs-wealth")
    assert "information" in gibbs and "Alpharetta" in gibbs
    assert not any(chr(cp) in gibbs for cp in (0x19F, 0x19E, 0x1A9, 0x1AF, 0x14C, 0xF0B7))


def test_each_firm_has_toc_chunks_and_only_toc_is_flagged(
    corpus: tuple[list[Chunk], list[DocSummary]],
) -> None:
    chunks, summaries = corpus
    toc = [c for c in chunks if c.is_toc]
    assert {c.doc_id for c in toc} == {s.doc_id for s in summaries}
    assert all(c.adv_item == 3 for c in toc)
    assert not any(c.is_toc and "Fees and Compensation We" in c.text for c in chunks)
