"""The LangGraph pipeline: retrieve -> generate -> finalize, built from config flags."""

import uuid
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentguard.agents.generator import Generator
from agentguard.config import Settings
from agentguard.llm import LLMClient
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


def _build_answer(
    question: str, retrieved: list[RetrievedChunk], output: GeneratorOutput
) -> Answer:
    return Answer(
        question=question,
        sentences=output.sentences,
        refused=output.refused,
        # No policy or verifier node yet (M7/M8): any baseline refusal is for lack of evidence.
        refusal_reason="insufficient_evidence" if output.refused else None,
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


def run_pipeline(question: str, settings: Settings) -> tuple[Answer, Trace]:
    """Build the real retriever, LLM client, and generator, then answer `question` once."""
    retriever = Retriever.from_settings(settings)
    generator = Generator(settings, LLMClient(settings))
    graph = build_graph(settings, retriever, generator)
    trace = Trace(query_id=uuid.uuid4().hex)
    initial: PipelineState = {
        "question": question,
        "trace": trace,
        "retrieved": [],
        "generator_output": None,
        "answer": None,
    }
    result = graph.invoke(initial)
    answer = result["answer"]
    assert answer is not None  # finalize_node always sets it
    return answer, trace
