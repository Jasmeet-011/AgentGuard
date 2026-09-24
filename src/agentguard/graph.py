"""The LangGraph pipeline: [decompose] -> retrieve -> generate -> [verify] -> finalize, from config flags.

`build_graph` is deliberately dumb: it wires nodes around a `Retriever` and `Generator`
it is handed. `pipeline.Pipeline` is what actually builds those (from shared, load-once
`Resources`) and runs the graph for a question.
"""

from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentguard.agents.decomposer import Decomposer
from agentguard.agents.generator import Generator
from agentguard.agents.verifier import Verifier
from agentguard.config import Settings
from agentguard.models import (
    Answer,
    CitedSentence,
    GeneratorOutput,
    RetrievedChunk,
    Trace,
    VerificationResult,
)
from agentguard.retrieval.retriever import Retriever

# Which milestone adds the node behind each not-yet-implemented flag.
UNIMPLEMENTED_NODES: dict[str, str] = {
    "enable_policy_guard": "M8 (policy_guard node)",
    "enable_score_threshold": "M9 (threshold_check node)",
}


class PipelineState(TypedDict):
    """State threaded through the graph for one query. `trace` is mutated in place."""

    question: str
    trace: Trace
    sub_queries: list[str]
    retrieved: list[RetrievedChunk]
    generator_output: GeneratorOutput | None
    verification: list[VerificationResult]
    removed_sentences: list[CitedSentence]
    verifier_rejected: bool
    answer: Answer | None


def _check_implemented(settings: Settings) -> None:
    """Fail loudly if a flag is on for a node this milestone does not build yet."""
    for flag, milestone in UNIMPLEMENTED_NODES.items():
        if getattr(settings, flag):
            raise NotImplementedError(
                f"{flag} is enabled, but its node is not implemented until {milestone}."
            )


# The generator's own refusal_kind, mapped to Answer's refusal_reason. There is no policy_guard
# node yet (M8), so an advice-request refusal from the generator's prompt-level guard (rule 7)
# is still reported as "policy"; anything else refused falls back to "insufficient_evidence".
_REFUSAL_REASON: dict[str | None, Literal["policy", "insufficient_evidence"]] = {
    "advice_request": "policy",
    "insufficient_evidence": "insufficient_evidence",
    None: "insufficient_evidence",
}


def _build_answer(state: PipelineState, output: GeneratorOutput) -> Answer:
    if state["verifier_rejected"]:
        reason: Literal["policy", "insufficient_evidence", "verifier_rejected"] | None = (
            "verifier_rejected"
        )
    elif output.refused:
        reason = _REFUSAL_REASON[output.refusal_kind]
    else:
        reason = None
    return Answer(
        question=state["question"],
        sentences=output.sentences,
        refused=output.refused,
        refusal_reason=reason,
        refusal_message=output.refusal_message,
        partial_note=output.partial_note,
        retrieved=state["retrieved"],
        verification=state["verification"],
        removed_sentences=state["removed_sentences"],
    )


def build_graph(
    settings: Settings,
    retriever: Retriever,
    generator: Generator,
    verifier: Verifier,
    decomposer: Decomposer,
) -> CompiledStateGraph:
    """Compile [decompose] -> retrieve -> generate -> [verify] -> finalize.

    `decompose` (before retrieval) and `verify` exist only if their flags are on.

    A generator refusal (or an empty answer) skips `verify`: there is nothing to check.
    Raises `NotImplementedError` if a flag for a node not yet built (policy_guard,
    threshold_check) is enabled, naming the milestone that adds it.
    """
    _check_implemented(settings)

    def decompose_node(state: PipelineState) -> dict[str, object]:
        return {"sub_queries": decomposer.decompose(state["question"], state["trace"])}

    def retrieve_node(state: PipelineState) -> dict[str, object]:
        found = retriever.retrieve(
            state["question"], state["trace"], sub_queries=state["sub_queries"] or None
        )
        return {"retrieved": found}

    def generate_node(state: PipelineState) -> dict[str, object]:
        output = generator.generate(state["question"], state["retrieved"], state["trace"])
        return {"generator_output": output}

    def verify_node(state: PipelineState) -> dict[str, object]:
        output = state["generator_output"]
        assert output is not None  # generate_node always sets it
        outcome = verifier.verify(output.sentences, state["retrieved"], state["trace"])
        if outcome.rejected:
            output = GeneratorOutput(
                sentences=[], refused=True, refusal_message=outcome.rejection_message
            )
        else:
            output = output.model_copy(update={"sentences": outcome.kept})
        return {
            "generator_output": output,
            "verification": outcome.verification,
            "removed_sentences": outcome.removed,
            "verifier_rejected": outcome.rejected,
        }

    def finalize_node(state: PipelineState) -> dict[str, object]:
        output = state["generator_output"]
        assert output is not None  # generate_node always sets it
        return {"answer": _build_answer(state, output)}

    def after_generate(state: PipelineState) -> Literal["verify", "finalize"]:
        output = state["generator_output"]
        has_sentences = output is not None and not output.refused and bool(output.sentences)
        return "verify" if has_sentences else "finalize"

    graph = StateGraph(PipelineState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("finalize", finalize_node)
    if settings.enable_decomposition:
        graph.add_node("decompose", decompose_node)
        graph.set_entry_point("decompose")
        graph.add_edge("decompose", "retrieve")
    else:
        graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    if settings.enable_verifier:
        graph.add_node("verify", verify_node)
        graph.add_conditional_edges("generate", after_generate)
        graph.add_edge("verify", "finalize")
    else:
        graph.add_edge("generate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
