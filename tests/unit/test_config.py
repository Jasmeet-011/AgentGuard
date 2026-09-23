from pathlib import Path

import pytest
from pydantic import ValidationError

from agentguard.config import PROJECT_ROOT, Settings

PATH_FIELDS = ("raw_dir", "processed_dir", "qdrant_path", "cache_dir", "results_dir")


@pytest.fixture(autouse=True)
def dummy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy-key-for-tests")


def test_settings_loads_with_dummy_key() -> None:
    settings = Settings()
    assert settings.generator_model == "claude-sonnet-5"
    assert "sk-dummy-key-for-tests" not in str(settings)
    assert "**********" in str(settings)


def test_project_root_is_repo_root() -> None:
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert (PROJECT_ROOT / "PLAN.md").is_file()


def test_settings_from_other_cwd_uses_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A decoy .env in the cwd must be ignored: only PROJECT_ROOT/.env is read.
    (tmp_path / ".env").write_text("DENSE_TOP_K=999\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert Settings.model_config["env_file"] == PROJECT_ROOT / ".env"
    assert settings.dense_top_k != 999
    for name in PATH_FIELDS:
        path = getattr(settings, name)
        assert path.is_absolute(), name
        assert path.is_relative_to(PROJECT_ROOT), name
    assert settings.raw_dir == PROJECT_ROOT / "data" / "raw"
    assert settings.cache_dir == PROJECT_ROOT / ".cache"


def test_relative_path_override_resolves_against_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CACHE_DIR", "tmp-cache")
    assert Settings().cache_dir == PROJECT_ROOT / "tmp-cache"


@pytest.mark.parametrize(
    "field", ["dense_top_k", "sparse_top_k", "rrf_k", "rerank_top_n", "llm_max_tokens"]
)
@pytest.mark.parametrize("value", [0, -1])
def test_counts_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match=field):
        Settings(**{field: value})


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_verifier_max_drop_ratio_bounded(value: float) -> None:
    with pytest.raises(ValidationError, match="verifier_max_drop_ratio"):
        Settings(verifier_max_drop_ratio=value)


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_verifier_max_drop_ratio_accepts_bounds(value: float) -> None:
    assert Settings(verifier_max_drop_ratio=value).verifier_max_drop_ratio == value


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_temperature_bounded(value: float) -> None:
    with pytest.raises(ValidationError, match="llm_temperature"):
        Settings(llm_temperature=value)


@pytest.mark.parametrize("overlap", [400, 500])
def test_overlap_must_be_less_than_target(overlap: int) -> None:
    with pytest.raises(ValidationError, match="chunk_overlap_tokens"):
        Settings(chunk_target_tokens=400, chunk_overlap_tokens=overlap)


def test_overlap_just_below_target_is_allowed() -> None:
    assert Settings(chunk_target_tokens=400, chunk_overlap_tokens=399).chunk_overlap_tokens == 399
