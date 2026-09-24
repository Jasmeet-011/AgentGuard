"""LLM judges for answer correctness (key facts present) and faithfulness (claims supported).

Both go through `LLMClient.complete_structured`, so judge calls are cached like any other.
"""

from typing import Literal

from pydantic import BaseModel

from agentguard.config import Settings
from agentguard.llm import LLMClient
from agentguard.models import Answer, Trace
from agentguard.prompts import load_prompt

CORRECTNESS_PROMPT = "judge_correctness"
FAITHFULNESS_PROMPT = "judge_faithfulness"


class JudgeError(Exception):
    """The judge's output did not cover exactly the items it was asked about."""


class KeyFactVerdict(BaseModel):
    """The judge's verdict on one key fact."""

    index: int
    present: bool
    reason: str


class CorrectnessVerdicts(BaseModel):
    """One verdict per key fact, in order, using the key fact's own number as `index`."""

    verdicts: list[KeyFactVerdict]


class SentenceVerdict(BaseModel):
    """The judge's verdict on one answer sentence."""

    sentence_index: int
    verdict: Literal["supported", "partial", "unsupported"]
    reason: str


class FaithfulnessVerdicts(BaseModel):
    """One verdict per sentence, using the sentence's own number as `sentence_index`."""

    verdicts: list[SentenceVerdict]


def answer_text(answer: Answer) -> str:
    """The answer's cited sentences joined into one paragraph (empty if refused)."""
    return " ".join(s.text for s in answer.sentences)


def _correctness_user(question: str, key_facts: list[str], answer: Answer) -> str:
    facts = "\n".join(f"{i}. {fact}" for i, fact in enumerate(key_facts, start=1))
    return f"Question: {question}\n\nKey facts:\n{facts}\n\nAnswer:\n{answer_text(answer)}"


def _faithfulness_user(answer: Answer) -> str:
    chunks = {r.chunk.chunk_id: r.chunk.text for r in answer.retrieved}
    blocks = []
    for i, sentence in enumerate(answer.sentences, start=1):
        cited = "\n\n".join(f"[{cid}]\n{chunks[cid]}" for cid in sentence.citations)
        blocks.append(f"Sentence {i}: {sentence.text}\nCited chunks:\n{cited}")
    return "\n\n---\n\n".join(blocks)


def _require_indices(got: list[int], expected: list[int], what: str) -> None:
    if sorted(got) != expected:
        raise JudgeError(f"Judge returned {what} indices {sorted(got)}, expected {expected}")


class Judge:
    """Scores answers with `settings.judge_model`."""

    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self._settings = settings
        self._llm = llm

    def key_fact_verdicts(
        self, question: str, key_facts: list[str], answer: Answer, trace: Trace
    ) -> list[KeyFactVerdict]:
        """One verdict per key fact, ordered by key fact. Raises `JudgeError` if any is missing."""
        result = self._llm.complete_structured(
            self._settings.judge_model,
            load_prompt(CORRECTNESS_PROMPT),
            _correctness_user(question, key_facts, answer),
            CorrectnessVerdicts,
            trace,
            "judge_correctness",
        )
        _require_indices(
            [v.index for v in result.verdicts], list(range(1, len(key_facts) + 1)), "key fact"
        )
        return sorted(result.verdicts, key=lambda v: v.index)

    def sentence_verdicts(self, answer: Answer, trace: Trace) -> list[SentenceVerdict]:
        """One verdict per answer sentence, in order. Raises `JudgeError` if any is missing."""
        result = self._llm.complete_structured(
            self._settings.judge_model,
            load_prompt(FAITHFULNESS_PROMPT),
            _faithfulness_user(answer),
            FaithfulnessVerdicts,
            trace,
            "judge_faithfulness",
        )
        _require_indices(
            [v.sentence_index for v in result.verdicts],
            list(range(1, len(answer.sentences) + 1)),
            "sentence",
        )
        return sorted(result.verdicts, key=lambda v: v.sentence_index)
