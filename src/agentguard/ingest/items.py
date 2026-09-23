"""ADV item vocabulary and line classifiers: item headings, TOC pages, Part 2B cover pages."""

import re

from agentguard.models import DocType

# Canonical item titles from the SEC Form ADV Part 2 instructions. Part 2A has Items 1-18
# plus Item 19 for state-registered advisers (Vanguard's brochure includes it).
ITEM_TITLES: dict[DocType, dict[int, str]] = {
    "part2a": {
        1: "Cover Page",
        2: "Material Changes",
        3: "Table of Contents",
        4: "Advisory Business",
        5: "Fees and Compensation",
        6: "Performance-Based Fees and Side-By-Side Management",
        7: "Types of Clients",
        8: "Methods of Analysis, Investment Strategies and Risk of Loss",
        9: "Disciplinary Information",
        10: "Other Financial Industry Activities and Affiliations",
        11: "Code of Ethics, Participation or Interest in Client Transactions and Personal Trading",
        12: "Brokerage Practices",
        13: "Review of Accounts",
        14: "Client Referrals and Other Compensation",
        15: "Custody",
        16: "Investment Discretion",
        17: "Voting Client Securities",
        18: "Financial Information",
        19: "Requirements for State-Registered Advisers",
    },
    "wrap_appendix1": {
        1: "Cover Page",
        2: "Material Changes",
        3: "Table of Contents",
        4: "Services, Fees and Compensation",
        5: "Account Requirements and Types of Clients",
        6: "Portfolio Manager Selection and Evaluation",
        7: "Client Information Provided to Portfolio Managers",
        8: "Client Contact with Portfolio Managers",
        9: "Additional Information",
    },
    "part2b": {},
}

# Items counted by the M2 acceptance check (Item 19 is optional for SEC-registered firms).
REQUIRED_ITEMS: dict[DocType, range] = {
    "part2a": range(1, 19),
    "wrap_appendix1": range(1, 10),
    "part2b": range(0),
}
TOC_ITEM = 3

# Distinctive leading phrase of each title, applied to normalize_heading() output. Variants
# seen in real brochures: "Summary of Material Changes", "Brochure Table of Contents",
# "Types of Members", "Member Referrals", "Performance Based" (no hyphen).
_TITLE_PATTERNS: dict[DocType, dict[int, str]] = {
    "part2a": {
        1: r"cover page",
        2: r"(summary of )?material changes",
        3: r"(brochure )?table of contents",
        4: r"advisory business",
        5: r"fees and compensation",
        6: r"performance based fees",
        7: r"types of (clients|members)",
        8: r"methods of analysis",
        9: r"disciplinary information",
        10: r"other financial industry activities",
        11: r"code of ethics",
        12: r"brokerage practices",
        13: r"review of accounts",
        14: r"(client|member) referrals",
        15: r"custody",
        16: r"investment discretion",
        17: r"voting (client |member )?securities",
        18: r"financial information",
        19: r"requirements for state registered advis[eo]rs",
    },
    "wrap_appendix1": {
        1: r"cover page",
        2: r"(summary of )?material changes",
        3: r"(wrap fee (program )?brochure )?table of contents",
        4: r"services fees and compensation",
        5: r"account requirements and types of clients",
        6: r"portfolio manager selection and evaluation",
        7: r"client information provided to portfolio managers",
        8: r"client contact with portfolio managers",
        9: r"additional information",
    },
    "part2b": {},
}

_ITEM_PREFIX = re.compile(r"^item (\d{1,2})(?: (.*))?$")
# "Item N <title>" lines longer than this are prose that happens to start with "Item N".
MAX_ITEM_HEADING_WORDS = 18
# A title-only heading may carry a few extra words (a run-in subheading, a TOC page number).
MAX_EXTRA_TITLE_WORDS = 3
_DOT_LEADER = re.compile(r"(\.\s*){4,}\d+\s*$")
TOC_MIN_HEADINGS = 8
TOC_MIN_DOT_LEADERS = 3
_PART2B_COVER = re.compile(r"^(form adv part 2b|part 2b of form adv)\b")
MAX_PART2B_COVER_WORDS = 8


def normalize_heading(line: str) -> str:
    """Lowercase, '&' -> 'and', punctuation -> spaces, collapse whitespace."""
    text = line.lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _title_match(item: int, text: str, doc_type: DocType) -> bool:
    pattern = _TITLE_PATTERNS[doc_type].get(item)
    return pattern is not None and re.match(rf"{pattern}\b", text) is not None


def match_item_heading(line: str, next_line: str | None, doc_type: DocType) -> int | None:
    """Item number if `line` is an explicit "Item N <title>" heading, else None.

    The title must match item N's canonical title, which rejects prose such as
    "Item 10 of this Brochure." A bare "Item N" line is accepted if `next_line` is the title.
    """
    text = normalize_heading(line)
    m = _ITEM_PREFIX.match(text)
    if m is None or len(text.split()) > MAX_ITEM_HEADING_WORDS:
        return None
    item, rest = int(m.group(1)), m.group(2)
    if rest is None:
        rest = normalize_heading(next_line or "")
    return item if _title_match(item, rest, doc_type) else None


def match_title_heading(line: str, doc_type: DocType) -> int | None:
    """Item number if `line` is a bare canonical title (no "Item N"), as Fisher/Vanguard use."""
    if not line[:1].isupper():
        return None
    text = normalize_heading(line)
    for item, pattern in _TITLE_PATTERNS[doc_type].items():
        title_words = len(normalize_heading(ITEM_TITLES[doc_type][item]).split())
        if re.match(rf"{pattern}\b", text) and (
            len(text.split()) <= title_words + MAX_EXTRA_TITLE_WORDS
        ):
            return item
    return None


def is_toc_page(lines: list[str], doc_type: DocType) -> bool:
    """True for a table-of-contents page: many item headings, or dot leaders to page numbers."""
    headings = 0
    leaders = 0
    for i, line in enumerate(lines):
        next_line = lines[i + 1] if i + 1 < len(lines) else None
        is_heading = (
            match_item_heading(line, next_line, doc_type) is not None
            or match_title_heading(line, doc_type) is not None
        )
        headings += is_heading
        leaders += is_heading and _DOT_LEADER.search(line) is not None
    return headings >= TOC_MIN_HEADINGS or leaders >= TOC_MIN_DOT_LEADERS


def is_part2b_cover(lines: list[str]) -> bool:
    """True if the page has a standalone "Form ADV Part 2B" / "Part 2B of Form ADV" line."""
    for line in lines:
        text = normalize_heading(line)
        if _PART2B_COVER.match(text) and len(text.split()) <= MAX_PART2B_COVER_WORDS:
            return True
    return False
