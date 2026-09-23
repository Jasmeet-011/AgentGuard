import pytest

from agentguard.ingest.items import (
    is_part2b_cover,
    is_toc_page,
    match_item_heading,
    match_title_heading,
    normalize_heading,
)

# Real "Item N" header lines from the brochures in data/raw (separator and case variants).
REAL_ITEM_HEADINGS = [
    ("Item 1 – Cover Page", 1),  # atwood: en dash
    ("Item 1- Cover Page", 1),  # atwood: hyphen, no space before
    ("Item 1. Cover Page", 1),  # facet: period
    ("Item 2: Material Changes", 2),  # edelman: colon
    ("Item 2 - Summary of Material Changes", 2),  # betterment: "Summary of"
    ("Item 3 - Brochure Table of Contents", 3),  # betterment: "Brochure" prefix
    ("Item 7 -Types of Clients", 7),  # savvy: no space after hyphen
    ("Item 7. Types of Members", 7),  # facet: "Members"
    ("Item 7 – Types of Clients & Account Minimums", 7),  # atwood: ampersand, extra words
    ("Item 9  - Disciplinary Information", 9),  # betterment: double space
    ("Item 6 Performance-Based Fees and Side--by--Side Management", 6),  # wealthfront
    ("Item 6 - Performance Based Fees and Side-by-Side Management", 6),  # savvy: no hyphen
    ("Item 11. Code of Ethics, Participation or Interest in Member: Transactions and", 11),
    ("Item 17. Voting Member Securities", 17),  # facet
    ("Item 5 – Fees and Compensation ..........................................", 5),
]


@pytest.mark.parametrize(("line", "item"), REAL_ITEM_HEADINGS)
def test_real_item_headings_match(line: str, item: int) -> None:
    assert match_item_heading(line, None, "part2a") == item


@pytest.mark.parametrize(
    "line",
    [
        "Item 10 of this Brochure.",  # gibbs: cross-reference that wrapped to line start
        "Item 5. Personal Advisor requires use of one of the custodians utilized in the Firm",
        "Item 4 - Types of Advisory Services for a description of the agreements that govern",
        "Item 3 - Disciplinary Information",  # atwood Part 2B: Item 3 is not Part 2A's Item 3
        "Items 4 and 5 describe our services.",
    ],
)
def test_prose_and_wrong_titles_do_not_match(line: str) -> None:
    assert match_item_heading(line, None, "part2a") is None


def test_bare_item_line_uses_next_line_as_title() -> None:
    assert match_item_heading("ITEM 5", "Fees and Compensation", "part2a") == 5
    assert match_item_heading("ITEM 2", "Educational Background", "part2a") is None


@pytest.mark.parametrize(
    ("line", "item"),
    [
        ("Item 4:  Services, Fees, and Compensation", 4),
        ("Item 5: Account Requirements and Types of Clients", 5),
        ("Item 3: Wrap Fee Brochure Table of Contents", 3),
        ("Item 9:  Additional Information", 9),
    ],
)
def test_wrap_appendix_headings_use_appendix_titles(line: str, item: int) -> None:
    assert match_item_heading(line, None, "wrap_appendix1") == item
    if item in (4, 5, 9):  # same number, different Part 2A title
        assert match_item_heading(line, None, "part2a") is None


# Real title-only headings (no "Item N") from fisher-investments.pdf and vanguard.
@pytest.mark.parametrize(
    ("line", "item"),
    [
        ("Fees and Compensation", 5),  # fisher
        ("Performance-Based Fees and Side-By-Side Management", 6),  # fisher
        ("Code of Ethics, Participation or Interest in Client Transactions and", 11),  # fisher
        ("Voting Client Securities", 17),  # fisher
        ("Fees and compensation Advisory fee", 5),  # vanguard: run-in subheading
        ("Methods of analysis, investment strategies, and risk of loss", 8),  # vanguard
        (
            "Code of ethics, participation or interest in client transactions, and personal trading",
            11,
        ),
        ("Requirements for state-registered advisors", 19),  # vanguard
    ],
)
def test_real_title_only_headings_match(line: str, item: int) -> None:
    assert match_title_heading(line, "part2a") == item


@pytest.mark.parametrize(
    "line",
    [
        "performance-based fee arrangements permit FI to receive compensation",  # lowercase body
        "FI does not typically charge performance-based fees for private client accounts",
        "Custody of client assets is maintained by an independent qualified custodian at all times",
    ],
)
def test_body_lines_are_not_title_headings(line: str) -> None:
    assert match_title_heading(line, "part2a") is None


def test_normalize_heading() -> None:
    assert normalize_heading("Item 7 – Types of Clients & Account Minimums") == (
        "item 7 types of clients and account minimums"
    )


# Real TOC page text (after parsing) from atwood-financial-planning.pdf page 3.
ATWOOD_TOC = [
    "Item 3 – Table of Contents",
    "Item 1 – Cover Page 1",
    "Item 2 – Material Changes 2",
    "Item 3 – Table of Contents 3",
    "Item 4 – Advisory Business 4",
    "Item 5 – Fees and Compensation 6",
    "Item 6 - Performance-Based Fees and Side-By-Side Management 8",
    "Item 7 – Types of Clients & Account Minimums 8",
    "Item 8 – Methods of Analysis, Investment Strategies, Investment Tools, and Risk of Loss 8",
    "Item 9 – Disciplinary Information 12",
    "Item 10 – Other Financial Industry Activities and Affiliations 12",
    "Item 11 – Code of Ethics, Participation or Interest in Client Transactions and Personal Trading12",
    "Item 12 – Brokerage Practices 13",
    "Item 13 – Review of Accounts 14",
    "Item 14 – Client Referrals and Other Compensation 15",
    "Item 15 – Custody 15",
    "Item 16 – Investment Discretion 15",
    "Item 17 – Voting Client Securities 15",
    "Item 18 – Financial Information 15",
    "Supervised Person Brochures 16",
]

# Real TOC page text from vanguard-personal-advisor.pdf page 2 (dot leaders, no "Item N").
VANGUARD_TOC = [
    "Contents",
    "Advisory business" + "." * 60 + "3",
    "Fees and compensation Advisory fee" + "." * 60 + "8",
    "Performance-based fees and side-by-side management" + "." * 40 + "13",
    "Types of clients" + "." * 60 + "13",
    "Disciplinary information" + "." * 60 + "19",
    "Custody" + "." * 60 + "25",
]

# Real content page from atwood page 15: five genuine item headings, but not a TOC.
ATWOOD_PAGE_15 = [
    "Service. Check-in meetings are conducted by the client’s advisor at Atwood Financial.",
    "Item 14 – Client Referrals and Other Compensation",
    "Atwood does not receive any economic benefits from external sources.",
    "Item 15 – Custody",
    "Atwood does not have custody of any client funds or securities.",
    "Item 16 – Investment Discretion",
    "Atwood only manages accounts on a non-discretionary basis.",
    "Item 17 – Voting Client Securities",
    "However, Atwood will not have authority to vote proxies on behalf of the Client.",
    "Item 18 – Financial Information",
    "A. Balance Sheet",
]


def test_toc_page_with_many_item_headings() -> None:
    assert is_toc_page(ATWOOD_TOC, "part2a")


def test_toc_page_with_dot_leaders_and_title_only_entries() -> None:
    assert is_toc_page(VANGUARD_TOC, "part2a")


def test_content_page_with_several_headings_is_not_toc() -> None:
    assert not is_toc_page(ATWOOD_PAGE_15, "part2a")


def test_part2b_cover_detected_but_not_prose_mentions() -> None:
    wealthfront_p39 = ["261 Hamilton Avenue", "Form ADV Part 2B", "Client Brochure Supplement"]
    edelman_p47 = ["March 31, 2026", "Part 2B of Form ADV: Brochure Supplement"]
    prose = ["please see the Firm’s Form ADV Part 2B for more about the Investment Committee"]
    assert is_part2b_cover(wealthfront_p39)
    assert is_part2b_cover(edelman_p47)
    assert not is_part2b_cover(prose)
