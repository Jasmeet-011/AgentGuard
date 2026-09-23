from pathlib import Path

import pytest

from agentguard.prompts import load_prompt


def test_load_prompt_reads_md_file(tmp_path: Path) -> None:
    (tmp_path / "greeting.md").write_text("Hello, advisor.", encoding="utf-8")
    assert load_prompt("greeting", prompts_dir=tmp_path) == "Hello, advisor."


def test_load_prompt_missing_lists_available(tmp_path: Path) -> None:
    (tmp_path / "exists.md").write_text("x", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="'exists'"):
        load_prompt("missing", prompts_dir=tmp_path)
