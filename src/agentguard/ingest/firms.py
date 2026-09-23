"""Load `data/raw/firms.json`: display name, aliases, and brochure type per PDF slug."""

import json
from pathlib import Path

from agentguard.models import FirmInfo

FIRMS_FILENAME = "firms.json"


class FirmsFileError(Exception):
    """firms.json is missing, malformed, or does not cover every PDF."""


def load_firms(raw_dir: Path) -> dict[str, FirmInfo]:
    """Read `{raw_dir}/firms.json` into FirmInfo models keyed by slug."""
    path = raw_dir / FIRMS_FILENAME
    if not path.is_file():
        raise FirmsFileError(f"{path} not found. It maps each PDF slug to its firm.")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {slug: FirmInfo(slug=slug, **entry) for slug, entry in data.items()}


def firm_for_pdf(pdf: Path, firms: dict[str, FirmInfo]) -> FirmInfo:
    """The firms.json entry for `pdf` (matched by file stem), or a clear error."""
    firm = firms.get(pdf.stem)
    if firm is None:
        raise FirmsFileError(
            f"No {FIRMS_FILENAME} entry for {pdf.name}. Add {pdf.stem!r}. Known: {sorted(firms)}"
        )
    return firm
