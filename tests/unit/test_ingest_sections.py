from agentguard.ingest.sections import (
    _Candidate,
    assign_doc_types,
    select_boundaries,
    split_sections,
)
from agentguard.models import FirmInfo, Page


def firm(**overrides: object) -> FirmInfo:
    fields: dict[str, object] = {
        "slug": "acme",
        "name": "Acme Advisors",
        "aliases": ["acme"],
        "doc_type": "part2a",
    }
    return FirmInfo(**(fields | overrides))  # type: ignore[arg-type]


def page(number: int, *paragraphs: list[str]) -> Page:
    return Page(doc_id="acme", page_number=number, paragraphs=list(paragraphs))


def cand(page_number: int, item: int, line_index: int = 0) -> _Candidate:
    return _Candidate(page_number=page_number, line_index=line_index, item=item, explicit=True)


def test_boundaries_skip_material_changes_summary_that_names_items_early() -> None:
    # creative-planning: page 2 lists Items 5, 7, 10 before the real Items 4, 5, 6, 7, ...
    summary = [cand(2, 5), cand(2, 7), cand(2, 10)]
    real = [cand(5, 4), cand(8, 5), cand(12, 6), cand(12, 7)]
    chosen = select_boundaries(summary + real)
    assert [(c.page_number, c.item) for c in chosen] == [(5, 4), (8, 5), (12, 6), (12, 7)]


def test_boundaries_prefer_earliest_duplicate() -> None:
    # fisher: "Methods of Analysis" is both the Item 8 heading and a subheading below it.
    chosen = select_boundaries([cand(7, 7), cand(8, 8, 0), cand(8, 8, 5), cand(9, 9)])
    assert [(c.item, c.line_index) for c in chosen] == [(7, 0), (8, 0), (9, 0)]


def test_split_sections_labels_items_and_leaves_preamble_unlabeled() -> None:
    pages = [
        page(1, ["Acme Advisors", "123 Main St"]),
        page(
            2,
            ["Fees paragraph ends previous item."],
            ["Item 4 – Advisory Business"],
            ["We advise."],
        ),
        page(3, ["Item 5: Fees and Compensation", "We charge 1%."]),
    ]
    sections = split_sections(pages, firm())
    assert [(s.adv_item, s.paragraphs[0].text) for s in sections] == [
        (None, "Acme Advisors 123 Main St"),
        (4, "Item 4 – Advisory Business"),
        (5, "Item 5: Fees and Compensation We charge 1%."),
    ]
    assert sections[1].paragraphs[1].page_number == 2


def test_heading_mid_paragraph_splits_the_paragraph() -> None:
    pages = [page(1, ["tail of the cover page", "Item 4 Advisory Business", "We advise."])]
    sections = split_sections(pages, firm())
    assert [s.paragraphs[0].text for s in sections] == [
        "tail of the cover page",
        "Item 4 Advisory Business We advise.",
    ]


def test_wrap_appendix_and_part2b_segments() -> None:
    pages = [
        page(1, ["Item 5 - Fees and Compensation", "Wrap fee is 0.25%."]),
        page(2, ["Form ADV Part 2A – Appendix 1"]),
        page(3, ["Item 5: Account Requirements and Types of Clients", "Minimum $0."]),
        page(4, ["Form ADV Part 2B", "Client Brochure Supplement"]),
        page(5, ["Item 3 - Disciplinary Information", "None."]),
    ]
    acme = firm(wrap_appendix1_from_page=2)
    assert assign_doc_types(pages, acme) == [
        "part2a",
        "wrap_appendix1",
        "wrap_appendix1",
        "part2b",
        "part2b",
    ]
    labeled = [(s.doc_type, s.adv_item) for s in split_sections(pages, acme)]
    assert labeled == [
        ("part2a", 5),
        ("wrap_appendix1", None),
        ("wrap_appendix1", 5),
        ("part2b", None),
    ]


def test_toc_page_listing_part2b_does_not_start_part2b() -> None:
    toc = [f"Item {n} – {title} {n}" for n, title in enumerate(TITLES, start=1)]
    pages = [page(1, toc + ["Form ADV Part 2B"]), page(2, ["Item 4 – Advisory Business"])]
    assert assign_doc_types(pages, firm()) == ["part2a", "part2a"]
    sections = split_sections(pages, firm())
    assert [s.adv_item for s in sections] == [3, 4]  # the TOC page itself is Item 3


TITLES = [
    "Cover Page",
    "Material Changes",
    "Table of Contents",
    "Advisory Business",
    "Fees and Compensation",
    "Performance-Based Fees and Side-By-Side Management",
    "Types of Clients",
    "Methods of Analysis, Investment Strategies and Risk of Loss",
    "Disciplinary Information",
]
