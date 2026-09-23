"""Prompt templates live in this directory as `.md` files, loaded by name."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    """Return the text of `{prompts_dir}/{name}.md`."""
    path = prompts_dir / f"{name}.md"
    if not path.is_file():
        available = sorted(p.stem for p in prompts_dir.glob("*.md"))
        raise FileNotFoundError(f"Prompt {name!r} not found at {path}. Available: {available}")
    return path.read_text(encoding="utf-8")
