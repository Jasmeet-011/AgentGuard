"""Golden dataset schema, loader validation, and summary."""

import json
from pathlib import Path

import pytest

from eval.golden import GoldenEntry, GoldenError, load_golden, select_entries, summary_counts

SLUGS = {"savvy", "facet"}
SOURCE = {"firm": "savvy", "doc_type": "part2a", "item": 5, "page": 9}


def entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "q1",
        "split": "dev",
        "type": "answerable",
        "question": "What is the minimum?",
        "expected_sources": [SOURCE],
        "key_facts": ["$500,000"],
        "verified": True,
    }
    return base | overrides


def write(tmp_path: Path, *entries: dict[str, object]) -> Path:
    path = tmp_path / "golden.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


def test_valid_file_loads_with_defaults(tmp_path: Path) -> None:
    (loaded,) = load_golden(write(tmp_path, entry()), SLUGS)
    assert loaded.match == "any"
    assert loaded.notes == ""


def test_the_committed_golden_file_is_valid_against_the_real_firms() -> None:
    from agentguard.config import PROJECT_ROOT
    from agentguard.ingest.firms import load_firms
    from eval.golden import GOLDEN_PATH

    slugs = set(load_firms(PROJECT_ROOT / "data" / "raw"))
    entries = load_golden(GOLDEN_PATH, slugs)
    assert {"q005", "q006"} <= {e.id for e in entries}


@pytest.mark.parametrize(
    "bad, message",
    [
        (entry(key_facts=[]), "non-empty key_facts"),
        (entry(expected_sources=[]), "non-empty expected_sources"),
        (entry(expected_sources=[{**SOURCE, "page": None}]), "page on every expected source"),
        (entry(type="unanswerable"), "must have empty"),
        (entry(type="policy", key_facts=[], expected_sources=[SOURCE]), "must have empty"),
        (entry(type="advice"), "type"),
        (entry(split="train"), "split"),
        (entry(match="some"), "match"),
        (entry(expected_sources=[{**SOURCE, "doc_type": "part9"}]), "doc_type"),
        (entry(unknown_field=1), "unknown_field"),
    ],
)
def test_invalid_entries_are_rejected(tmp_path: Path, bad: dict[str, object], message: str) -> None:
    with pytest.raises(GoldenError, match=message):
        load_golden(write(tmp_path, bad), SLUGS)


def test_unanswerable_and_policy_with_empty_fields_are_valid(tmp_path: Path) -> None:
    empty = {"expected_sources": [], "key_facts": []}
    path = write(
        tmp_path,
        entry(id="u1", type="unanswerable", **empty),
        entry(id="p1", type="policy", split="TBD", **empty),
    )
    assert len(load_golden(path, SLUGS)) == 2


def test_duplicate_ids_and_unknown_slugs_are_reported_together(tmp_path: Path) -> None:
    other = {**SOURCE, "firm": "nope"}
    path = write(tmp_path, entry(), entry(), entry(id="q2", expected_sources=[other]))
    with pytest.raises(GoldenError) as exc:
        load_golden(path, SLUGS)
    assert "duplicate id 'q1'" in str(exc.value)
    assert "unknown firm slug 'nope'" in str(exc.value)


def test_invalid_json_line_is_reported_with_its_line_number(tmp_path: Path) -> None:
    path = tmp_path / "golden.jsonl"
    path.write_text(json.dumps(entry()) + '\n{"id": "q2", "page": PAGE}\n', encoding="utf-8")
    with pytest.raises(GoldenError, match="line 2: not valid JSON"):
        load_golden(path, SLUGS)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(GoldenError, match="not found"):
        load_golden(tmp_path / "nope.jsonl", SLUGS)


def test_select_entries_uses_only_verified_entries_of_the_split() -> None:
    entries = [
        GoldenEntry.model_validate(entry(id="a")),
        GoldenEntry.model_validate(entry(id="b", verified=False)),
        GoldenEntry.model_validate(entry(id="c", split="test")),
        GoldenEntry.model_validate(entry(id="d", split="TBD")),
    ]
    assert [e.id for e in select_entries(entries, "dev")] == ["a"]
    assert [e.id for e in select_entries(entries, "test")] == ["c"]


def test_summary_counts_total_and_verified() -> None:
    entries = [
        GoldenEntry.model_validate(entry(id="a")),
        GoldenEntry.model_validate(entry(id="b", verified=False)),
    ]
    assert summary_counts(entries) == {("answerable", "dev"): (2, 1)}
