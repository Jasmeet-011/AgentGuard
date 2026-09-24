"""Typed records for one eval run: per-question rows and the aggregate."""

from typing import Literal

from pydantic import BaseModel, Field

from eval.golden import EntryType


class QuestionResult(BaseModel):
    """Everything measured for one golden question under one variant."""

    id: str
    type: EntryType
    question: str
    refused: bool
    refusal_reason: str | None
    answer_text: str
    retrieved_chunk_ids: list[str]
    # answerable only
    retrieval_hit: bool | None = None
    correctness: float | None = None
    correctness_reasons: list[str] = Field(default_factory=list)
    # answerable and not refused only
    faithfulness: float | None = None
    faithfulness_reasons: list[str] = Field(default_factory=list)
    # all questions
    invalid_citations: int = 0
    total_citations: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0


class Aggregate(BaseModel):
    """Run-level metrics. None means no question the metric applies to (or no denominator)."""

    n_answerable: int
    n_unanswerable: int
    n_policy: int
    retrieval_recall: float | None
    correctness: float | None
    faithfulness: float | None
    invalid_citation_rate: float | None
    correct_refusal_rate: float | None
    false_refusal_rate: float | None
    policy_block_rate: float | None
    policy_reason_rate: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    cost_per_query_usd: float | None


class RunResult(BaseModel):
    """One `agentguard eval` run for one variant on one split."""

    variant: str
    split: Literal["dev", "test"]
    timestamp: str
    preliminary: bool
    verified_in_file: int
    unverified_skipped: int
    top_k: int
    config: dict[str, object]
    aggregate: Aggregate
    rows: list[QuestionResult]
