"""Run the golden set through pipeline variants and record metrics (`agentguard eval`)."""

import logging
from datetime import UTC, datetime

from agentguard.config import Settings
from agentguard.ingest.firms import load_firms
from agentguard.models import Answer, Trace
from agentguard.pipeline import Pipeline
from eval import metrics
from eval.golden import GOLDEN_PATH, GoldenEntry, load_golden, select_entries
from eval.judge import Judge, answer_text
from eval.records import FactVerdictRecord, QuestionResult, RunResult, SentenceVerdictRecord

logger = logging.getLogger(__name__)

# A variant is a named set of `Pipeline.with_overrides` fields. All optional components stay
# off in these three; later milestones add "+verifier", "+policy", "+threshold" and "full".
VARIANTS: dict[str, dict[str, object]] = {
    "dense": {
        "retrieval_mode": "dense",
        "enable_verifier": False,
        "enable_policy_guard": False,
        "enable_score_threshold": False,
    },
    "hybrid": {
        "retrieval_mode": "hybrid",
        "enable_verifier": False,
        "enable_policy_guard": False,
        "enable_score_threshold": False,
    },
    "baseline": {
        "retrieval_mode": "hybrid_rerank",
        "enable_verifier": False,
        "enable_policy_guard": False,
        "enable_score_threshold": False,
    },
}


def _judge_answerable(
    entry: GoldenEntry, answer: Answer, judge: Judge, row: QuestionResult
) -> None:
    """Fill correctness (always) and faithfulness (only if the answer has sentences).

    Judge calls record into their own trace, never the pipeline's, so they cannot leak into
    latency or pipeline cost; their cost goes to `row.judge_cost_usd`.
    """
    if answer.refused or not answer.sentences:
        row.correctness = 0.0
        return
    judge_trace = Trace(query_id=f"judge-{entry.id}")
    facts = judge.key_fact_verdicts(entry.question, entry.key_facts, answer, judge_trace)
    row.correctness = metrics.key_fact_score([v.present for v in facts])
    row.fact_verdicts = [
        FactVerdictRecord(key_fact=entry.key_facts[v.index - 1], present=v.present, reason=v.reason)
        for v in facts
    ]
    sentences = judge.sentence_verdicts(answer, judge_trace)
    row.faithfulness = metrics.faithfulness_score([v.verdict for v in sentences])
    row.sentence_verdicts = [
        SentenceVerdictRecord(
            sentence=answer.sentences[v.sentence_index - 1].text, verdict=v.verdict, reason=v.reason
        )
        for v in sentences
    ]
    row.judge_cost_usd = metrics.latency_and_cost(judge_trace)[1]


def evaluate_question(entry: GoldenEntry, pipeline: Pipeline, judge: Judge) -> QuestionResult:
    """Run one golden question through `pipeline` and score it."""
    answer, trace = pipeline.run(entry.question)
    invalid, total = metrics.invalid_citation_counts(answer, trace)
    latency_ms, cost_usd = metrics.latency_and_cost(trace)
    row = QuestionResult(
        id=entry.id,
        type=entry.type,
        question=entry.question,
        refused=answer.refused,
        refusal_reason=answer.refusal_reason,
        answer_text=answer_text(answer),
        retrieved_chunk_ids=[r.chunk.chunk_id for r in answer.retrieved],
        invalid_citations=invalid,
        total_citations=total,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )
    if entry.type == "answerable":
        row.retrieval_hit = metrics.retrieval_hit([r.chunk for r in answer.retrieved], entry)
        _judge_answerable(entry, answer, judge, row)
    return row


def _config_snapshot(settings: Settings) -> dict[str, object]:
    return {
        "retrieval_mode": settings.retrieval_mode,
        "rerank_top_n": settings.rerank_top_n,
        "dense_top_k": settings.dense_top_k,
        "sparse_top_k": settings.sparse_top_k,
        "reranker_model": settings.reranker_model,
        "generator_model": settings.generator_model,
        "judge_model": settings.judge_model,
        "enable_verifier": settings.enable_verifier,
        "enable_policy_guard": settings.enable_policy_guard,
        "enable_score_threshold": settings.enable_score_threshold,
        "min_rerank_score": settings.min_rerank_score,
    }


def run_variant(
    variant: str,
    split: str,
    base: Pipeline,
    settings: Settings,
    entries: list[GoldenEntry],
) -> RunResult:
    """Evaluate every verified entry of `split` under `variant`. `entries` is the whole file."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown variant {variant!r}. Known: {sorted(VARIANTS)}")
    if split not in ("dev", "test"):
        raise ValueError(f"split must be 'dev' or 'test', got {split!r}")
    selected = select_entries(entries, split)
    if not selected:
        raise ValueError(f"No verified entries in split {split!r}; nothing to evaluate.")
    pipeline = base.with_overrides(**VARIANTS[variant])
    judge = Judge(settings, base.resources.llm)
    # One untimed query first: the first inference in a process is slower (torch warm-up, lazy
    # buffers), and that cost must not land on the first question's latency.
    logger.info("[%s/%s] warm-up (untimed): %s", variant, split, selected[0].id)
    pipeline.run(selected[0].question)
    rows = []
    for entry in selected:
        logger.info("[%s/%s] %s", variant, split, entry.id)
        rows.append(evaluate_question(entry, pipeline, judge))
    verified = sum(e.verified for e in entries)
    return RunResult(
        variant=variant,
        split=split,  # type: ignore[arg-type]  # validated above
        timestamp=datetime.now(UTC).strftime("%Y%m%dT%H%M%S"),
        preliminary=verified < settings.eval_min_verified_for_final,
        verified_in_file=verified,
        unverified_skipped=len(entries) - verified,
        top_k=settings.rerank_top_n,
        config=_config_snapshot(settings.model_copy(update=VARIANTS[variant])),
        aggregate=metrics.aggregate(rows),
        rows=rows,
    )


def load_entries(settings: Settings) -> list[GoldenEntry]:
    """Load and validate the golden file against the firms in `settings.raw_dir`."""
    return load_golden(GOLDEN_PATH, set(load_firms(settings.raw_dir)))
