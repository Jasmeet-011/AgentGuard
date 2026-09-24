"""End-to-end baseline pipeline: real retrieval indexes, real generator LLM calls."""

import pytest

from agentguard.config import Settings
from agentguard.graph import run_pipeline


def settings() -> Settings:
    return Settings()


@pytest.mark.integration
def test_answerable_questions_have_citations_resolving_to_retrieved_chunks() -> None:
    questions = [
        "What is Savvy's minimum account size?",
        "What fees does Fisher Investments charge?",
        "Has Vanguard been subject to any SEC enforcement action?",
    ]
    for question in questions:
        answer, trace = run_pipeline(question, settings())
        assert answer.refused is False, f"{question!r} was refused: {answer.refusal_message}"
        assert answer.sentences, f"{question!r} returned no sentences"
        valid_ids = {r.chunk.chunk_id for r in answer.retrieved}
        for sentence in answer.sentences:
            assert sentence.citations, f"{question!r}: uncited sentence {sentence.text!r}"
            for chunk_id in sentence.citations:
                assert chunk_id in valid_ids, f"{question!r}: unresolved citation {chunk_id!r}"
        assert trace.total_cost_usd > 0


@pytest.mark.integration
def test_savvy_minimum_account_size_states_the_verified_figure() -> None:
    answer, _ = run_pipeline("What is Savvy's minimum account size?", settings())
    assert answer.refused is False
    joined = " ".join(s.text for s in answer.sentences)
    assert "500,000" in joined


@pytest.mark.integration
def test_unanswerable_question_is_refused() -> None:
    answer, _ = run_pipeline("What is Savvy's CEO's favorite restaurant?", settings())
    assert answer.refused is True
    assert answer.refusal_reason == "insufficient_evidence"
    assert answer.refusal_message
    assert answer.sentences == []
