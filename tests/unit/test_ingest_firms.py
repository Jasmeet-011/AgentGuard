import json
from pathlib import Path

import pytest

from agentguard.config import Settings
from agentguard.ingest.firms import FirmsFileError, firm_for_pdf, load_firms, match_firms
from agentguard.models import FirmInfo


def test_load_firms_reads_entries(tmp_path: Path) -> None:
    entry = {"name": "Acme", "aliases": ["acme"], "doc_type": "part2a"}
    (tmp_path / "firms.json").write_text(json.dumps({"acme": entry}), encoding="utf-8")
    firms = load_firms(tmp_path)
    assert firms["acme"].slug == "acme"
    assert firms["acme"].wrap_appendix1_from_page is None


def test_missing_firms_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FirmsFileError, match="firms.json not found"):
        load_firms(tmp_path)


def test_pdf_without_entry_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FirmsFileError, match="No firms.json entry for mystery.pdf"):
        firm_for_pdf(tmp_path / "mystery.pdf", {})


def test_repo_firms_json_covers_every_pdf() -> None:
    raw_dir = Settings(anthropic_api_key="sk-test").raw_dir
    firms = load_firms(raw_dir)
    pdfs = sorted(raw_dir.glob("*.pdf"))
    assert pdfs
    assert {pdf.stem for pdf in pdfs} == set(firms)
    assert all(alias == alias.lower() for firm in firms.values() for alias in firm.aliases)
    assert firms["betterment"].wrap_appendix1_from_page == 35


@pytest.fixture(scope="module")
def repo_firms() -> dict[str, FirmInfo]:
    return load_firms(Settings(anthropic_api_key="sk-test").raw_dir)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("What fees does Fisher Investments charge?", ["fisher-investments"]),
        ("What are the fees for Betterment's wrap fee program?", ["betterment"]),
        ("Betterment’s fees", ["betterment"]),  # curly apostrophe
        ("Compare Wealthfront and Betterment advisory fees", ["wealthfront", "betterment"]),
        ("Does Gibbs Wealth Management have custody?", ["gibbs-wealth"]),
        ("VANGUARD enforcement", ["vanguard-personal-advisor"]),
        ("Which firms charge a flat annual fee?", []),
        # Word boundaries: ordinary words that contain an alias do not match.
        ("Do fishermen use savvyness or unsavvy vanguardism?", []),
        ("financial engines advisors", ["edelman-financial-engines"]),
    ],
)
def test_match_firms(repo_firms: dict[str, FirmInfo], query: str, expected: list[str]) -> None:
    assert match_firms(query, repo_firms) == expected


def test_match_firms_orders_by_first_mention(repo_firms: dict[str, FirmInfo]) -> None:
    query = "Gibbs vs Atwood vs Gibbs Wealth"
    assert match_firms(query, repo_firms) == ["gibbs-wealth", "atwood-financial-planning"]
