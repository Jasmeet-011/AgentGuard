"""Application settings: all tunable flags, thresholds, and paths live here."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root (src/agentguard/config.py -> parents[2]). All paths resolve against this,
# so behavior does not depend on the current working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Per-million-token USD prices (base input / output), keyed by model name.
# Source: https://platform.claude.com/docs/en/about-claude/pricing, fetched 2026-09-23.
MODEL_PRICES_PER_MILLION_TOKENS: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 2.0, "output": 10.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
}

# Models that reject `temperature` (API returns 400 "`temperature` is deprecated for this
# model"; per the API reference, models released after Claude Opus 4.6 do not support it).
# `llm_temperature` is sent only to models NOT in this set.
MODELS_WITHOUT_TEMPERATURE: frozenset[str] = frozenset({"claude-sonnet-5"})


class Settings(BaseSettings):
    """Central configuration, loaded from environment variables and `PROJECT_ROOT/.env`."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8")

    anthropic_api_key: SecretStr

    generator_model: str = "claude-sonnet-5"
    verifier_model: str = "claude-sonnet-5"
    judge_model: str = "claude-sonnet-5"
    policy_model: str = "claude-haiku-4-5-20251001"

    enable_llm_cache: bool = True
    llm_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    llm_max_tokens: int = Field(default=2048, gt=0)
    llm_retry_attempts: int = Field(default=5, ge=1)

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"

    chunk_target_tokens: int = Field(default=400, gt=0)
    chunk_overlap_tokens: int = Field(default=60, ge=0)

    dense_top_k: int = Field(default=20, gt=0)
    sparse_top_k: int = Field(default=20, gt=0)
    rrf_k: int = Field(default=60, gt=0)
    rerank_top_n: int = Field(default=6, gt=0)

    retrieval_mode: Literal["dense", "hybrid", "hybrid_rerank"] = "hybrid_rerank"

    enable_policy_guard: bool = True
    enable_verifier: bool = True
    enable_score_threshold: bool = True

    min_rerank_score: float = 0.0
    verifier_max_drop_ratio: float = Field(default=0.5, ge=0.0, le=1.0)

    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    processed_dir: Path = PROJECT_ROOT / "data" / "processed"
    qdrant_path: Path = PROJECT_ROOT / "data" / "processed" / "qdrant"
    cache_dir: Path = PROJECT_ROOT / ".cache"
    results_dir: Path = PROJECT_ROOT / "eval" / "results"

    @field_validator(
        "raw_dir", "processed_dir", "qdrant_path", "cache_dir", "results_dir", mode="after"
    )
    @classmethod
    def _resolve_against_project_root(cls, path: Path) -> Path:
        """Relative overrides (e.g. from `.env`) are taken relative to PROJECT_ROOT, not cwd."""
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @model_validator(mode="after")
    def _overlap_smaller_than_target(self) -> Self:
        if self.chunk_overlap_tokens >= self.chunk_target_tokens:
            raise ValueError(
                f"chunk_overlap_tokens ({self.chunk_overlap_tokens}) must be less than "
                f"chunk_target_tokens ({self.chunk_target_tokens})"
            )
        return self
