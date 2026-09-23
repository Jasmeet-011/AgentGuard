import random
from itertools import pairwise

import pytest

from agentguard.ingest.chunk import (
    MAX_FILL,
    MIN_FILL,
    Unit,
    chunk_header,
    chunk_sections,
    estimate_tokens,
    pack_units,
    section_units,
)
from agentguard.ingest.sections import Paragraph, Section
from agentguard.models import FirmInfo

TARGET = 400
OVERLAP = 60
ACME = FirmInfo(slug="acme", name="Acme Advisors", aliases=["acme"], doc_type="part2a")


def random_section(seed: int, paragraphs: int = 40) -> Section:
    """Deterministic prose: paragraphs of 1-8 sentences, sentences of 5-60 words."""
    rng = random.Random(seed)
    paras = []
    for p in range(paragraphs):
        sentences = [
            " ".join(f"w{rng.randint(0, 999)}" for _ in range(rng.randint(5, 60))).capitalize()
            + "."
            for _ in range(rng.randint(1, 8))
        ]
        paras.append(Paragraph(page_number=1 + p // 5, text=" ".join(sentences)))
    return Section(doc_type="part2a", adv_item=5, paragraphs=paras)


def sizes(chunks: list[list[Unit]]) -> list[int]:
    return [sum(u.tokens for u in chunk) for chunk in chunks]


def test_estimate_tokens_is_words_times_1_3_rounded_up() -> None:
    assert estimate_tokens("one two three") == 4
    assert estimate_tokens("") == 0


@pytest.mark.parametrize("seed", range(5))
def test_chunks_stay_within_30_percent_of_target(seed: int) -> None:
    section = random_section(seed)
    packed = pack_units(section_units(section, TARGET), TARGET, OVERLAP)
    *full, last = sizes(packed)
    assert len(full) >= 5
    assert all(MIN_FILL * TARGET <= s <= MAX_FILL * TARGET for s in full), full
    assert last <= MAX_FILL * TARGET


def test_rendered_chunk_bodies_are_within_30_percent_of_target() -> None:
    chunks = chunk_sections([random_section(7)], ACME, TARGET, OVERLAP)
    bodies = [estimate_tokens(c.text.split("\n", 1)[1]) for c in chunks]
    assert all(0.7 * TARGET <= b <= 1.3 * TARGET for b in bodies[:-1]), bodies


def shared_words(prev: list[Unit], nxt: list[Unit]) -> int:
    """Length of the longest suffix of `prev` (in words) that `nxt` starts with."""
    a = " ".join(u.text for u in prev).split()
    b = " ".join(u.text for u in nxt).split()
    return max((k for k in range(1, min(len(a), len(b)) + 1) if a[-k:] == b[:k]), default=0)


def test_consecutive_chunks_overlap() -> None:
    packed = pack_units(section_units(random_section(1), TARGET), TARGET, OVERLAP)
    assert len(packed) >= 5
    for prev, nxt in pairwise(packed):
        k = shared_words(prev, nxt)
        assert k >= 1
        assert estimate_tokens(" ".join(["w"] * k)) <= OVERLAP


def test_overlap_falls_back_to_word_tail_for_long_last_sentence() -> None:
    long_sentence = " ".join(["word"] * 150) + "."  # ~195 tokens, longer than OVERLAP
    section = Section(
        doc_type="part2a",
        adv_item=8,
        paragraphs=[Paragraph(page_number=1, text=long_sentence)] * 6,
    )
    packed = pack_units(section_units(section, TARGET), TARGET, OVERLAP)
    assert len(packed) >= 2
    carried = packed[1][0]
    assert 0 < carried.tokens <= OVERLAP
    assert " ".join(u.text for u in packed[0]).endswith(carried.text)


def test_chunks_prefer_to_end_at_paragraph_boundaries() -> None:
    # Paragraphs of ~130 tokens: a paragraph end past 70% of target always exists.
    para = " ".join(["alpha"] * 50) + ". " + " ".join(["beta"] * 50) + "."
    section = Section(
        doc_type="part2a", adv_item=4, paragraphs=[Paragraph(page_number=1, text=para)] * 12
    )
    packed = pack_units(section_units(section, TARGET), TARGET, OVERLAP)
    assert all(chunk[-1].paragraph_end for chunk in packed)


def test_long_sentence_is_split_into_pieces() -> None:
    section = Section(
        doc_type="part2a",
        adv_item=5,
        paragraphs=[Paragraph(page_number=3, text=" ".join(["fee"] * 400))],
    )
    units = section_units(section, TARGET)
    assert len(units) > 1
    assert all(u.tokens <= TARGET * 0.5 + 1 for u in units)
    assert [u.paragraph_end for u in units][-1] is True


def test_small_section_is_one_chunk() -> None:
    section = Section(
        doc_type="part2a",
        adv_item=16,
        paragraphs=[
            Paragraph(page_number=9, text="Acme only manages accounts non-discretionarily.")
        ],
    )
    [chunk] = chunk_sections([section], ACME, TARGET, OVERLAP)
    assert chunk.text == (
        "Acme Advisors | Item 16: Investment Discretion\n"
        "Acme only manages accounts non-discretionarily."
    )
    assert (chunk.page_start, chunk.page_end, chunk.adv_item) == (9, 9, 16)
    assert chunk.is_toc is False


def test_toc_section_flag_carries_to_every_chunk() -> None:
    section = random_section(4).model_copy(update={"adv_item": 3, "is_toc": True})
    chunks = chunk_sections([section], ACME, TARGET, OVERLAP)
    assert len(chunks) > 1
    assert all(c.is_toc for c in chunks)


def test_chunk_ids_are_unique_and_stable_across_runs() -> None:
    sections = [random_section(2), random_section(3)]
    first = [c.chunk_id for c in chunk_sections(sections, ACME, TARGET, OVERLAP)]
    second = [c.chunk_id for c in chunk_sections(sections, ACME, TARGET, OVERLAP)]
    assert first == second
    assert len(set(first)) == len(first)
    assert first[0] == "acme-p1-0"


def test_chunk_headers() -> None:
    def header(doc_type: str, item: int | None) -> str:
        section = Section(doc_type=doc_type, adv_item=item, paragraphs=[])  # type: ignore[arg-type]
        return chunk_header("Betterment", section)

    assert header("part2a", 5) == "Betterment | Item 5: Fees and Compensation"
    assert header("wrap_appendix1", 5) == (
        "Betterment | Wrap Fee Brochure Item 5: Account Requirements and Types of Clients"
    )
    assert header("part2a", None) == "Betterment | Form ADV Part 2A"
    assert header("part2b", None) == "Betterment | Form ADV Part 2B Brochure Supplement"
