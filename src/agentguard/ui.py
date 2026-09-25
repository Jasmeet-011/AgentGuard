"""Pure view-model helpers for the Streamlit app: no Streamlit import, so they are unit-tested."""

from pydantic import BaseModel

from agentguard.models import Answer, Chunk, Trace
from agentguard.trace import event_values

DEMO_QUESTIONS: tuple[str, ...] = (
    "What is Savvy's minimum account size?",
    "Has Vanguard's advisory business been subject to any SEC enforcement action?",
    (
        "What does Wealthfront charge on an Automated Investing Account, and has it faced "
        "any SEC enforcement action?"
    ),
    (
        "How does Wealthfront's annual fee on an Automated Investing Account compare with "
        "Betterment's Digital wrap fee?"
    ),
    "What were Fisher Investments' client returns in 2025?",
    "What is the home address of Atwood Financial Planning's founder?",
    "What is Atwood Financial Planning's business address?",
)

# Shown next to a demo question in the dropdown; the text sent to the pipeline is unchanged.
DEMO_TAGS: dict[int, str] = {
    2: "decomposition demo",
    4: "unanswerable, hard negative",
    5: "blocked",
    6: "allowed",
}

# Use-case group per demo question index, shown as a prefix in the dropdown label.
DEMO_GROUPS: dict[int, str] = {
    0: "Due diligence",
    1: "Due diligence",
    2: "Due diligence",
    3: "Due diligence",
    4: "Honest refusal",
    5: "Guardrails",
    6: "Guardrails",
}

RETRIEVAL_MODES: tuple[str, ...] = ("dense", "hybrid", "hybrid_rerank")


class TraceRow(BaseModel):
    """One trace event as displayed: cached events carry their original values."""

    node: str
    ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool


def escape_dollars(text: str) -> str:
    """Escape "$" so st.markdown does not treat text between two dollar signs as LaTeX math."""
    return text.replace("$", r"\$")


def strip_header(chunk: Chunk) -> str:
    """Chunk text without its retrieval header line ("{firm} | Item N: title"), for display only."""
    first, sep, rest = chunk.text.partition("\n")
    if sep and first.startswith(f"{chunk.firm_name} | "):
        return rest
    return chunk.text


def demo_label(index: int) -> str:
    """Dropdown label for demo question `index`: use-case group, the question, and its tag."""
    question = DEMO_QUESTIONS[index]
    tag = DEMO_TAGS.get(index)
    return f"{DEMO_GROUPS[index]} · {index + 1}. {question}" + (f" ({tag})" if tag else "")


def trace_rows(trace: Trace) -> list[TraceRow]:
    """Per-node rows for the trace panel; cached events show their original values."""
    rows = []
    for event in trace.events:
        ms, tokens_in, tokens_out, cost = event_values(event)
        rows.append(
            TraceRow(
                node=event.node,
                ms=ms,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                cost_usd=cost,
                cached=bool(event.detail.get("cached")),
            )
        )
    return rows


def sub_queries(trace: Trace) -> list[str]:
    """The decomposer's sub-queries when decomposition split the question, else empty."""
    for event in trace.events:
        if event.node == "decompose":
            found = event.detail.get("sub_queries", [])
            return list(found) if len(found) > 1 else []
    return []


def policy_category(trace: Trace) -> str | None:
    """The policy guard's category for this query, or None when the guard did not run."""
    for event in trace.events:
        if event.node == "policy_guard":
            return event.detail.get("category")
    return None


class Citation(BaseModel):
    """One numbered citation: the chunk behind it, ready to render."""

    number: int
    chunk: Chunk

    @property
    def label(self) -> str:
        item = "unlabeled" if self.chunk.adv_item is None else f"Item {self.chunk.adv_item}"
        return f"{self.chunk.firm_name} | {item} | {self.pages}"

    @property
    def pages(self) -> str:
        start, end = self.chunk.page_start, self.chunk.page_end
        return f"page {start}" if start == end else f"pages {start}-{end}"


class RenderedSentence(BaseModel):
    """An answer sentence with its citation numbers and whether the verifier called it partial."""

    text: str
    numbers: list[int]
    partial: bool


class RenderedAnswer(BaseModel):
    """An answer's sentences and the numbered citations they refer to."""

    sentences: list[RenderedSentence]
    citations: list[Citation]


def render_answer(answer: Answer) -> RenderedAnswer:
    """Number citations in order of first use, and pair each sentence with its numbers."""
    chunks = {r.chunk.chunk_id: r.chunk for r in answer.retrieved}
    numbers: dict[str, int] = {}
    verdicts = answer.kept_verification()
    sentences = []
    for i, sentence in enumerate(answer.sentences):
        marks = [numbers.setdefault(cid, len(numbers) + 1) for cid in sentence.citations]
        partial = bool(verdicts) and verdicts[i].verdict == "partial"
        sentences.append(RenderedSentence(text=sentence.text, numbers=marks, partial=partial))
    citations = [Citation(number=n, chunk=chunks[cid]) for cid, n in numbers.items()]
    return RenderedAnswer(sentences=sentences, citations=citations)


def removed_with_reasons(answer: Answer) -> list[tuple[str, str]]:
    """(sentence, reason) for each sentence the verifier removed."""
    unsupported = [v for v in answer.verification if v.verdict == "unsupported"]
    return [(s.text, v.reason) for s, v in zip(answer.removed_sentences, unsupported, strict=True)]
