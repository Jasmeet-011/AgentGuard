"""The golden eval dataset: schema, loader with validation, and a type x split summary."""

import json
from collections import Counter
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agentguard.models import DocType

GOLDEN_PATH = Path(__file__).parent / "golden.jsonl"

EntryType = Literal["answerable", "unanswerable", "policy"]
Split = Literal["dev", "test", "TBD"]
ENTRY_TYPES: tuple[str, ...] = ("answerable", "unanswerable", "policy")
SPLITS: tuple[str, ...] = ("dev", "test", "TBD")


class GoldenError(Exception):
    """The golden file is invalid. The message lists every problem found, with line numbers."""


class ExpectedSource(BaseModel):
    """Where an answer's evidence lives. `page` is documentation only; it is not matched on."""

    model_config = ConfigDict(extra="forbid")

    firm: str
    doc_type: DocType
    item: int = Field(ge=1)
    page: int | None = Field(default=None, ge=1)


class GoldenEntry(BaseModel):
    """One eval question. `match="any"`: one expected source suffices; `"all"`: every one is needed."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    split: Split
    type: EntryType
    question: str = Field(min_length=1)
    expected_sources: list[ExpectedSource] = Field(default_factory=list)
    match: Literal["any", "all"] = "any"
    key_facts: list[str] = Field(default_factory=list)
    notes: str = ""
    verified: bool = False

    @model_validator(mode="after")
    def _check_type_consistency(self) -> Self:
        if self.type == "answerable":
            if not self.key_facts:
                raise ValueError("answerable entries need non-empty key_facts")
            if not self.expected_sources:
                raise ValueError("answerable entries need non-empty expected_sources")
            if any(source.page is None for source in self.expected_sources):
                raise ValueError("answerable entries need a page on every expected source")
        elif self.key_facts or self.expected_sources:
            raise ValueError(f"{self.type} entries must have empty key_facts and expected_sources")
        return self

    @property
    def expected_firms(self) -> list[str]:
        """Distinct firms named in `expected_sources`, in order of first appearance."""
        return list(dict.fromkeys(source.firm for source in self.expected_sources))


def _parse_line(line_no: int, line: str) -> tuple[GoldenEntry | None, list[str]]:
    try:
        return GoldenEntry.model_validate_json(line), []
    except ValidationError as exc:
        problems = [
            f"line {line_no}: {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
        ]
        return None, problems


def _check_entries(entries: list[GoldenEntry], valid_slugs: set[str]) -> list[str]:
    problems: list[str] = []
    for entry_id, count in Counter(e.id for e in entries).items():
        if count > 1:
            problems.append(f"duplicate id {entry_id!r} ({count} entries)")
    for entry in entries:
        for source in entry.expected_sources:
            if source.firm not in valid_slugs:
                problems.append(
                    f"{entry.id}: unknown firm slug {source.firm!r}; valid: {sorted(valid_slugs)}"
                )
    return problems


def load_golden(path: Path, valid_slugs: set[str]) -> list[GoldenEntry]:
    """Load and validate `path`. Raises `GoldenError` listing every problem found."""
    if not path.is_file():
        raise GoldenError(f"Golden file not found: {path}")
    entries: list[GoldenEntry] = []
    problems: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"line {line_no}: not valid JSON: {exc}")
            continue
        entry, line_problems = _parse_line(line_no, line)
        problems.extend(line_problems)
        if entry is not None:
            entries.append(entry)
    problems.extend(_check_entries(entries, valid_slugs))
    if problems:
        raise GoldenError(f"{path} has {len(problems)} problem(s):\n" + "\n".join(problems))
    return entries


def select_entries(entries: list[GoldenEntry], split: str) -> list[GoldenEntry]:
    """Verified entries of `split`. Unverified entries are never used in evals."""
    return [e for e in entries if e.verified and e.split == split]


def summary_counts(entries: list[GoldenEntry]) -> dict[tuple[str, str], tuple[int, int]]:
    """(type, split) -> (total, verified)."""
    counts: dict[tuple[str, str], tuple[int, int]] = {}
    for entry in entries:
        total, verified = counts.get((entry.type, entry.split), (0, 0))
        counts[(entry.type, entry.split)] = (total + 1, verified + int(entry.verified))
    return counts
