"""Judge coverage checks, run assembly, and result files, with fake LLM and pipeline."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agentguard.config import Settings
from agentguard.models import Answer, Chunk, CitedSentence, RetrievedChunk, Trace, TraceEvent
from eval.golden import GoldenEntry
from eval.judge import (
    CorrectnessVerdicts,
    FaithfulnessVerdicts,
    Judge,
    JudgeError,
    KeyFactVerdict,
    SentenceVerdict,
)
from eval.report import comparison_markdown, is_failure, latest_runs, write_comparison, write_run
from eval.run_eval import VARIANTS, run_variant


def settings() -> Settings:
    return Settings(anthropic_api_key="sk-test")


CHUNK = Chunk(
    chunk_id="savvy-p9-0",
    firm_name="Savvy",
    doc_id="savvy",
    doc_type="part2a",
    adv_item=5,
    is_toc=False,
    item_title="Fees",
    page_start=9,
    page_end=9,
    text="Fees are 1% and negotiable.",
    token_count=5,
)


def make_answer(refused: bool = False) -> Answer:
    sentences = [] if refused else [CitedSentence(text="Fees are 1%.", citations=["savvy-p9-0"])]
    return Answer(
        question="?",
        sentences=sentences,
        refused=refused,
        refusal_reason="insufficient_evidence" if refused else None,
        refusal_message=None,
        retrieved=[RetrievedChunk(chunk=CHUNK)],
        verification=[],
        removed_sentences=[],
    )


class FakeLLM:
    """Returns canned judge verdicts and records each call."""

    def __init__(self, facts: list[bool], sentence_verdict: str = "supported") -> None:
        self.facts = facts
        self.sentence_verdict = sentence_verdict
        self.calls: list[tuple[str, str]] = []

    def complete_structured(
        self, model: str, system: str, user: str, output_model: type, trace: Trace, node: str
    ) -> Any:
        self.calls.append((node, user))
        trace.events.append(
            TraceEvent(node=node, started_at=datetime.now(UTC), duration_ms=9000, cost_usd=0.5)
        )
        if output_model is CorrectnessVerdicts:
            return CorrectnessVerdicts(
                verdicts=[
                    KeyFactVerdict(index=i, present=p, reason="r")
                    for i, p in enumerate(self.facts, 1)
                ]
            )
        return FaithfulnessVerdicts(
            verdicts=[SentenceVerdict(sentence_index=1, verdict=self.sentence_verdict, reason="r")]  # type: ignore[arg-type]
        )


def test_judge_sees_the_cited_chunk_text_and_the_key_facts() -> None:
    llm = FakeLLM([True])
    judge = Judge(settings(), llm)  # type: ignore[arg-type]
    judge.key_fact_verdicts("What fee?", ["1% fee"], make_answer(), Trace(query_id="j"))
    judge.sentence_verdicts(make_answer(), Trace(query_id="j"))
    assert "1. 1% fee" in llm.calls[0][1]
    assert "Fees are 1%." in llm.calls[0][1]
    assert "Fees are 1% and negotiable." in llm.calls[1][1]  # the cited chunk's full text


def test_judge_raises_when_a_key_fact_verdict_is_missing() -> None:
    judge = Judge(settings(), FakeLLM([True]))  # type: ignore[arg-type]
    with pytest.raises(JudgeError, match="key fact"):
        judge.key_fact_verdicts("?", ["a", "b"], make_answer(), Trace(query_id="j"))


class FakePipeline:
    def __init__(self, llm: FakeLLM, answer: Answer) -> None:
        self.resources = type("R", (), {"llm": llm})()
        self._answer = answer
        self.overrides: list[dict[str, object]] = []
        self.questions_run: list[str] = []

    def with_overrides(self, **updates: object) -> "FakePipeline":
        self.overrides.append(updates)
        return self

    def run(self, question: str) -> tuple[Answer, Trace]:
        self.questions_run.append(question)
        trace = Trace(query_id="p")
        trace.events.append(
            TraceEvent(node="generate", started_at=datetime.now(UTC), duration_ms=5, cost_usd=0.01)
        )
        return self._answer, trace


def golden_entries(n_verified: int = 1) -> list[GoldenEntry]:
    entries = []
    for i in range(n_verified):
        entries.append(
            GoldenEntry.model_validate(
                {
                    "id": f"q{i}",
                    "split": "dev",
                    "type": "answerable",
                    "question": "Fee?",
                    "expected_sources": [
                        {"firm": "savvy", "doc_type": "part2a", "item": 5, "page": 9}
                    ],
                    "key_facts": ["1%", "negotiable"],
                    "verified": True,
                }
            )
        )
    entries.append(
        GoldenEntry.model_validate({**entries[0].model_dump(), "id": "u", "verified": False})
    )
    return entries


def test_run_variant_scores_a_question_and_marks_the_run_preliminary() -> None:
    pipeline = FakePipeline(FakeLLM([True, False]), make_answer())
    run = run_variant("baseline", "dev", pipeline, settings(), golden_entries())  # type: ignore[arg-type]
    assert pipeline.overrides == [VARIANTS["baseline"]]
    # One untimed warm-up query, then the one verified question; the warm-up is not a row.
    assert pipeline.questions_run == ["Fee?", "Fee?"]
    assert len(run.rows) == 1
    assert run.preliminary  # 1 verified < 20
    assert (run.verified_in_file, run.unverified_skipped) == (1, 1)
    assert [r.id for r in run.rows] == ["q0"]  # the unverified entry was not run
    row = run.rows[0]
    assert row.retrieval_hit is True
    assert row.correctness == 0.5
    assert row.faithfulness == 1.0
    # Pipeline latency and cost exclude the judge's events (9000 ms, $0.5 each, 2 calls).
    assert (row.latency_ms, row.cost_usd) == (5, 0.01)
    assert row.judge_cost_usd == 1.0
    assert [f.present for f in row.fact_verdicts] == [True, False]
    assert row.sentence_verdicts[0].verdict == "supported"
    assert run.aggregate.eval_cost_per_question_usd == 1.0
    assert not is_failure(row)  # correctness 0.5 is not < 0.5, faithfulness is 1.0


def test_refused_answerable_scores_zero_without_calling_the_judge() -> None:
    llm = FakeLLM([True, True])
    pipeline = FakePipeline(llm, make_answer(refused=True))
    run = run_variant("baseline", "dev", pipeline, settings(), golden_entries())  # type: ignore[arg-type]
    assert run.rows[0].correctness == 0.0
    assert run.rows[0].faithfulness is None
    assert [n for n, _ in llm.calls] == []  # no judge call
    assert run.rows[0].judge_cost_usd == 0.0
    assert is_failure(run.rows[0])


def test_run_variant_rejects_unknown_variant_and_empty_split() -> None:
    pipeline = FakePipeline(FakeLLM([True]), make_answer())
    with pytest.raises(ValueError, match="Unknown variant"):
        run_variant("nope", "dev", pipeline, settings(), golden_entries())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="No verified entries"):
        run_variant("baseline", "test", pipeline, settings(), golden_entries())  # type: ignore[arg-type]


def test_results_files_and_latest_comparison(tmp_path: Path) -> None:
    pipeline = FakePipeline(FakeLLM([True, True]), make_answer())
    older = run_variant("baseline", "dev", pipeline, settings(), golden_entries())  # type: ignore[arg-type]
    older.timestamp = "20260101T000000"
    newer = older.model_copy(update={"timestamp": "20260102T000000"})
    newer.aggregate = newer.aggregate.model_copy(update={"correctness": 0.25})
    other = older.model_copy(update={"variant": "dense", "timestamp": "20260103T000000"})
    for run in (older, newer, other):
        json_path, md_path = write_run(run, tmp_path)
        assert json_path.is_file() and md_path.is_file()
    latest = latest_runs(tmp_path)
    assert set(latest) == {("dev", "baseline"), ("dev", "dense")}
    assert latest[("dev", "baseline")].timestamp == "20260102T000000"
    text = comparison_markdown(latest)
    assert "PRELIMINARY" in text
    assert "| Metric | baseline | dense |" in text
    assert "25.0%" in text  # the newer baseline run's correctness
    assert write_comparison(tmp_path).name == "latest_comparison.md"


def test_every_variant_sets_the_optional_components_explicitly() -> None:
    """A variant must not inherit a default flag: flipping a default would change old variants."""
    flags = {"enable_verifier", "enable_decomposition", "enable_policy_guard"}
    for name, overrides in VARIANTS.items():
        assert flags <= overrides.keys(), name
    assert VARIANTS["baseline"]["enable_decomposition"] is False
    assert VARIANTS["+decompose"]["enable_decomposition"] is True
