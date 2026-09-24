"""Pydantic data contracts shared by every component of the pipeline."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

# Which brochure a page belongs to. A PDF can hold several: Betterment's has a Part 2A,
# a wrap fee program brochure (Part 2A Appendix 1), and Part 2B supplements.
DocType = Literal["part2a", "wrap_appendix1", "part2b"]


class FirmInfo(BaseModel):
    """One firm's entry in `data/raw/firms.json`, keyed by the PDF's filename slug."""

    slug: str
    name: str
    aliases: list[str]
    doc_type: Literal["part2a", "wrap_appendix1"]
    wrap_appendix1_from_page: int | None = None


class Page(BaseModel):
    """One cleaned PDF page: paragraphs of lines, headers/footers and bad glyphs removed."""

    doc_id: str
    page_number: int
    paragraphs: list[list[str]]


class Chunk(BaseModel):
    """A retrievable slice of one ADV brochure, labeled with its ADV item."""

    chunk_id: str
    firm_name: str
    doc_id: str
    doc_type: DocType
    adv_item: int | None
    # True for table-of-contents text: it names every item, so M3 keeps it out of the indexes.
    is_toc: bool
    item_title: str | None
    page_start: int
    page_end: int
    text: str
    token_count: int


class RetrievedChunk(BaseModel):
    """A chunk plus the scores each retrieval stage assigned it (None if the stage did not run)."""

    chunk: Chunk
    dense_score: float | None = None
    sparse_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None


class CitedSentence(BaseModel):
    """One answer sentence and the chunk_ids it cites. Every sentence must cite something."""

    text: str
    citations: list[str] = Field(min_length=1)


class VerificationResult(BaseModel):
    """The verifier's verdict on one answer sentence.

    `sentence_index` is the sentence's 1-based position in the generator's sentence list.
    """

    sentence_index: int
    verdict: Literal["supported", "partial", "unsupported"]
    reason: str


class PolicyDecision(BaseModel):
    """The policy guard's classification of a question."""

    category: Literal["allowed", "personalized_advice", "pii_request", "out_of_scope"]
    reason: str


class GeneratorOutput(BaseModel):
    """Structured output of the generator LLM call: cited sentences, or a refusal."""

    sentences: list[CitedSentence] = Field(default_factory=list)
    refused: bool
    refusal_message: str | None = None
    refusal_kind: Literal["insufficient_evidence", "advice_request"] | None = Field(
        default=None,
        description=(
            "Set only when refused is true: 'insufficient_evidence' if none of the "
            "provided chunks are relevant (rule 6), 'advice_request' if the question "
            "asks for personalized investment advice (rule 7)."
        ),
    )
    partial_note: str | None = Field(
        default=None,
        description=(
            "Set only when the provided chunks answer part of the question: a plain "
            "statement of what is not covered. Leave unset if the question is fully "
            "answered, or if refused is true."
        ),
    )


class Answer(BaseModel):
    """Final pipeline output for one question."""

    question: str
    sentences: list[CitedSentence]
    refused: bool
    refusal_reason: Literal["policy", "insufficient_evidence", "verifier_rejected"] | None
    refusal_message: str | None
    # Set when the answer covers only part of the question; see `GeneratorOutput.partial_note`.
    partial_note: str | None = None
    retrieved: list[RetrievedChunk]
    verification: list[VerificationResult]
    removed_sentences: list[CitedSentence]

    def kept_verification(self) -> list[VerificationResult]:
        """Verdicts of the sentences that were kept, aligned one-to-one with `sentences`.

        `verification` covers every sentence the generator wrote, including removed ones.
        Empty when the verifier did not run or the answer was rejected.
        """
        kept = [v for v in self.verification if v.verdict != "unsupported"]
        return kept if len(kept) == len(self.sentences) else []


class TraceEvent(BaseModel):
    """Timing, token usage, and cost for one node execution."""

    node: str
    started_at: datetime
    duration_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    detail: dict[str, Any] = Field(default_factory=dict)


class Trace(BaseModel):
    """All events recorded while answering one query."""

    query_id: str
    events: list[TraceEvent] = Field(default_factory=list)

    @computed_field
    @property
    def total_ms(self) -> float:
        return sum(event.duration_ms for event in self.events)

    @computed_field
    @property
    def total_cost_usd(self) -> float:
        return sum(event.cost_usd for event in self.events)

    @computed_field
    @property
    def total_tokens(self) -> int:
        return sum(event.input_tokens + event.output_tokens for event in self.events)
