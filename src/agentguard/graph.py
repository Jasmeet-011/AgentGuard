"""The LangGraph pipeline: retrieve -> generate -> finalize, built from config flags.

`build_graph` is deliberately dumb: it wires nodes around a `Retriever` and `Generator`
it is handed. `pipeline.Pipeline` is what actually builds those (from shared, load-once
`Resources`) and runs the graph for a question.
"""

from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentguard.agents.generator import Generator
from agentguard.config import Settings
from agentguard.models import Answer, GeneratorOutput, RetrievedChunk, Trace
from agentguard.retrieval.retriever import Retriever

# Which milestone adds the node behind each not-yet-implemented flag.
UNIMPLEMENTED_NODES: dict[str, str] = {
    "enable_policy_guard": "M8 (policy_guard node)",
    "enable_verifier": "M7 (verify node)",
    "enable_score_threshold": "M9 (threshold_check node)",
}


class PipelineState(TypedDict):
    """State threaded through the graph for one query. `trace` is mutated in place."""

    question: str
    trace: Trace
    retrieved: list[RetrievedChunk]
    generator_output: GeneratorOutput | None
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


def _build_answer(
    question: str, retrieved: list[RetrievedChunk], output: GeneratorOutput
) -> Answer:
    return Answer(
        question=question,
        sentences=output.sentences,
        refused=output.refused,
        refusal_reason=_REFUSAL_REASON[output.refusal_kind] if output.refused else None,
        refusal_message=output.refusal_message,
        partial_note=output.partial_note,
        retrieved=retrieved,
        verification=[],
        removed_sentences=[],
    )


def build_graph(
    settings: Settings, retriever: Retriever, generator: Generator
) -> CompiledStateGraph:
    """Compile the baseline retrieve -> generate -> finalize graph.

    Raises `NotImplementedError` if a flag for a node not yet built (verify, policy_guard,
    threshold_check) is enabled, naming the milestone that adds it.
    """
    _check_implemented(settings)

    def retrieve_node(state: PipelineState) -> dict[str, object]:
        return {"retrieved": retriever.retrieve(state["question"], state["trace"])}

    def generate_node(state: PipelineState) -> dict[str, object]:
        output = generator.generate(state["question"], state["retrieved"], state["trace"])
        return {"generator_output": output}

    def finalize_node(state: PipelineState) -> dict[str, object]:
        output = state["generator_output"]
        assert output is not None  # generate_node always sets it
        return {"answer": _build_answer(state["question"], state["retrieved"], output)}

    graph = StateGraph(PipelineState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("finalize", finalize_node)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
