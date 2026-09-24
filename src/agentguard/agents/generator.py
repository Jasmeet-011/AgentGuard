"""The generator: turns retrieved chunks into cited sentences, or a refusal."""

import logging

from agentguard.config import Settings
from agentguard.llm import LLMClient
from agentguard.models import CitedSentence, GeneratorOutput, RetrievedChunk, Trace
from agentguard.prompts import load_prompt

logger = logging.getLogger(__name__)

GENERATOR_PROMPT = "generator_system"
GENERATOR_NODE_NAME = "generate"


def _chunk_context_block(index: int, retrieved: RetrievedChunk) -> str:
    """One numbered context entry: chunk_id, firm, doc_type, item, pages, then the text."""
    chunk = retrieved.chunk
    item = "unlabeled" if chunk.adv_item is None else f"{chunk.adv_item} ({chunk.item_title})"
    return (
        f"[{index}] chunk_id: {chunk.chunk_id}\n"
        f"Firm: {chunk.firm_name}\n"
        f"Doc type: {chunk.doc_type}\n"
        f"Item: {item}\n"
        f"Pages: {chunk.page_start}-{chunk.page_end}\n"
        f"Text:\n{chunk.text}"
    )


def _build_user_message(question: str, retrieved: list[RetrievedChunk]) -> str:
    context = "\n\n".join(_chunk_context_block(i, r) for i, r in enumerate(retrieved, start=1))
    return f"Question: {question}\n\nChunks:\n{context}"


def _drop_invalid_citations(
    output: GeneratorOutput, valid_ids: set[str], event_detail: dict[str, object]
) -> GeneratorOutput:
    """Remove citations to chunk_ids that were not retrieved; drop sentences left with none."""
    kept: list[CitedSentence] = []
    dropped_citations = 0
    dropped_sentences = 0
    for sentence in output.sentences:
        citations = [c for c in sentence.citations if c in valid_ids]
        dropped_citations += len(sentence.citations) - len(citations)
        if not citations:
            dropped_sentences += 1
            continue
        kept.append(CitedSentence(text=sentence.text, citations=citations))
    if dropped_citations or dropped_sentences:
        event_detail["invalid_citations_dropped"] = dropped_citations
        event_detail["sentences_dropped"] = dropped_sentences
        logger.warning(
            "Dropped %d invalid citation(s) and %d sentence(s) left with no valid citation",
            dropped_citations,
            dropped_sentences,
        )
    return GeneratorOutput(
        sentences=kept,
        refused=output.refused,
        refusal_message=output.refusal_message,
        partial_note=output.partial_note,
    )


class Generator:
    """Answers a question from retrieved chunks, with per-sentence citations or a refusal."""

    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self._settings = settings
        self._llm = llm

    def generate(
        self, question: str, retrieved: list[RetrievedChunk], trace: Trace
    ) -> GeneratorOutput:
        """Call the generator LLM, then drop any citation to a chunk_id that was not retrieved."""
        system = load_prompt(GENERATOR_PROMPT)
        user = _build_user_message(question, retrieved)
        raw = self._llm.complete_structured(
            self._settings.generator_model,
            system,
            user,
            GeneratorOutput,
            trace,
            GENERATOR_NODE_NAME,
        )
        valid_ids = {r.chunk.chunk_id for r in retrieved}
        return _drop_invalid_citations(raw, valid_ids, trace.events[-1].detail)
