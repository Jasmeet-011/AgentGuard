"""The verifier: checks every answer sentence against its cited chunks, drops unsupported ones."""

import logging

from pydantic import BaseModel

from agentguard.config import Settings
from agentguard.llm import LLMClient
from agentguard.models import CitedSentence, RetrievedChunk, Trace, VerificationResult
from agentguard.prompts import load_prompt

logger = logging.getLogger(__name__)

VERIFIER_PROMPT = "verifier_system"
VERIFIER_NODE_NAME = "verify"


class VerifierError(Exception):
    """The verifier's output did not cover exactly the sentences it was given."""


class VerifierOutput(BaseModel):
    """One verdict per answer sentence, using the sentence's own number as sentence_index."""

    results: list[VerificationResult]


class VerificationOutcome(BaseModel):
    """What verification did to an answer's sentences.

    `verification` holds one result per original sentence; its `sentence_index` is the
    sentence's 1-based position in the list the verifier was given, so it still lines up
    after `kept` and `removed` split that list.
    """

    kept: list[CitedSentence]
    removed: list[CitedSentence]
    verification: list[VerificationResult]
    rejected: bool
    rejection_message: str | None = None


def _sentence_block(number: int, sentence: CitedSentence, chunk_texts: dict[str, str]) -> str:
    cited = "\n\n".join(f"[{cid}]\n{chunk_texts[cid]}" for cid in sentence.citations)
    return f"Sentence {number}: {sentence.text}\nCited chunks:\n{cited}"


def build_user_message(sentences: list[CitedSentence], retrieved: list[RetrievedChunk]) -> str:
    """Numbered sentences (from 1), each followed by the full text of the chunks it cites."""
    chunk_texts = {r.chunk.chunk_id: r.chunk.text for r in retrieved}
    unknown = {c for s in sentences for c in s.citations} - chunk_texts.keys()
    if unknown:
        raise VerifierError(f"Sentences cite chunk_ids that were not retrieved: {sorted(unknown)}")
    blocks = [_sentence_block(i, s, chunk_texts) for i, s in enumerate(sentences, start=1)]
    return "\n\n---\n\n".join(blocks)


def apply_verdicts(
    sentences: list[CitedSentence], results: list[VerificationResult], max_drop_ratio: float
) -> VerificationOutcome:
    """Split `sentences` by verdict: `unsupported` are removed, `partial` and `supported` kept.

    The answer is rejected when the removed fraction exceeds `max_drop_ratio`, or when nothing
    is left. Raises `VerifierError` unless `results` has exactly one entry per sentence.
    """
    numbers = sorted(r.sentence_index for r in results)
    if numbers != list(range(1, len(sentences) + 1)):
        raise VerifierError(
            f"Verifier returned sentence_index values {numbers}, expected 1..{len(sentences)}"
        )
    ordered = sorted(results, key=lambda r: r.sentence_index)
    kept = [s for s, r in zip(sentences, ordered, strict=True) if r.verdict != "unsupported"]
    removed = [s for s, r in zip(sentences, ordered, strict=True) if r.verdict == "unsupported"]
    rejected = not kept or len(removed) / len(sentences) > max_drop_ratio
    message = None
    if rejected:
        message = (
            f"The verifier removed {len(removed)} of {len(sentences)} sentences as unsupported "
            "by their cited sources, so the answer was rejected rather than shown."
        )
    return VerificationOutcome(
        kept=kept,
        removed=removed,
        verification=ordered,
        rejected=rejected,
        rejection_message=message,
    )


class Verifier:
    """Checks answer sentences against their cited chunks with `settings.verifier_model`."""

    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self._settings = settings
        self._llm = llm

    def verify(
        self, sentences: list[CitedSentence], retrieved: list[RetrievedChunk], trace: Trace
    ) -> VerificationOutcome:
        """Verify all `sentences` in one batched LLM call and apply the verdicts.

        The removed and partial counts are logged on the verify trace event's detail.
        """
        output = self._llm.complete_structured(
            self._settings.verifier_model,
            load_prompt(VERIFIER_PROMPT),
            build_user_message(sentences, retrieved),
            VerifierOutput,
            trace,
            VERIFIER_NODE_NAME,
        )
        outcome = apply_verdicts(sentences, output.results, self._settings.verifier_max_drop_ratio)
        detail = trace.events[-1].detail
        detail["sentences_checked"] = len(sentences)
        detail["sentences_removed"] = len(outcome.removed)
        detail["sentences_partial"] = sum(r.verdict == "partial" for r in outcome.verification)
        detail["rejected"] = outcome.rejected
        if outcome.removed:
            logger.warning(
                "Verifier removed %d of %d sentence(s)", len(outcome.removed), len(sentences)
            )
        return outcome
