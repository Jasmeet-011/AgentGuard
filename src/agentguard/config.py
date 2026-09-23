"""Application settings: all tunable flags, thresholds, and paths live here."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Per-million-token USD prices, keyed by model name.
# Source: https://docs.claude.com/en/docs/about-claude/pricing (checked 2026-09-23).
MODEL_PRICES_PER_MILLION_TOKENS: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
}


class Settings(BaseSettings):
    """Central configuration, loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: SecretStr

    generator_model: str = "claude-sonnet-5"
    verifier_model: str = "claude-sonnet-5"
    judge_model: str = "claude-sonnet-5"
    policy_model: str = "claude-haiku-4-5-20251001"

    enable_llm_cache: bool = True
    llm_max_tokens: int = 2048
    llm_retry_attempts: int = 5

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"

    chunk_target_tokens: int = 400
    chunk_overlap_tokens: int = 60

    dense_top_k: int = 20
    sparse_top_k: int = 20
    rrf_k: int = 60
    rerank_top_n: int = 6

    retrieval_mode: Literal["dense", "hybrid", "hybrid_rerank"] = "hybrid_rerank"

    enable_policy_guard: bool = True
    enable_verifier: bool = True
    enable_score_threshold: bool = True

    min_rerank_score: float = 0.0
    verifier_max_drop_ratio: float = 0.5

    raw_dir: Path = Path("data/raw")
    processed_dir: Path = Path("data/processed")
    qdrant_path: Path = Path("data/processed/qdrant")
    cache_dir: Path = Path(".cache")
    results_dir: Path = Path("eval/results")
