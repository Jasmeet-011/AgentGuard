"""Typed records for one eval run: per-question rows and the aggregate."""

from typing import Literal

from pydantic import BaseModel, Field

from eval.golden import EntryType


class FactVerdictRecord(BaseModel):
    """The correctness judge's verdict on one key fact."""

    key_fact: str
    present: bool
    reason: str


class SentenceVerdictRecord(BaseModel):
    """The faithfulness judge's verdict on one answer sentence."""

    sentence: str
    verdict: str
    reason: str


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
    fact_verdicts: list[FactVerdictRecord] = Field(default_factory=list)
    # answerable and not refused only
    faithfulness: float | None = None
    sentence_verdicts: list[SentenceVerdictRecord] = Field(default_factory=list)
    # all questions. latency_ms and cost_usd are the pipeline's only; judge calls run on a
    # separate trace and are reported as judge_cost_usd.
    invalid_citations: int = 0
    total_citations: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    judge_cost_usd: float = 0.0


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
    # Judge cost averaged over every question (0 for questions that need no judge call).
    eval_cost_per_question_usd: float | None


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
