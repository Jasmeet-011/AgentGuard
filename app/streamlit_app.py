"""AgentGuard demo UI. Run with `make app`. Tabs: Ask (live pipeline) and Evals (stored results)."""

from typing import TYPE_CHECKING

import streamlit as st
from evals_tab import render as render_evals

from agentguard.config import Settings
from agentguard.models import Answer, Trace
from agentguard.ui import (
    DEMO_QUESTIONS,
    RETRIEVAL_MODES,
    demo_label,
    escape_dollars,
    policy_category,
    removed_with_reasons,
    render_answer,
    strip_header,
    sub_queries,
    trace_rows,
)

if TYPE_CHECKING:
    from agentguard.pipeline import Pipeline

SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
CUSTOM = "Custom question (free text)"


@st.cache_resource(show_spinner="Loading models and indexes (first run only)...")
def load_base() -> "Pipeline":
    """Load `Resources` once per process; every toggle combination shares them.

    `agentguard.pipeline` is imported here, not at module top: it pulls in torch (~10 s), which the
    Evals tab does not need.
    """
    from agentguard.pipeline import Pipeline

    return Pipeline.from_settings(Settings())


@st.cache_resource
def pipeline_for(mode: str, verifier: bool, decomposition: bool, guard: bool) -> "Pipeline":
    """A pipeline for one toggle combination over the shared `Resources` (no model reload)."""
    return load_base().with_overrides(
        retrieval_mode=mode,
        enable_verifier=verifier,
        enable_decomposition=decomposition,
        enable_policy_guard=guard,
    )


def marker(numbers: list[int]) -> str:
    """Superscript citation marker such as ¹˒³."""
    return "˒".join(str(n).translate(SUPERSCRIPT) for n in numbers)


def show_sub_queries(trace: Trace) -> None:
    subs = sub_queries(trace)
    if subs:
        lines = "\n".join(f"{i}. {q}" for i, q in enumerate(subs, 1))
        st.info(f"**Decomposed into sub-queries:**\n\n{lines}")


def show_citation(number: int, label: str, chunk_text: str, details: str) -> None:
    with st.expander(f"{str(number).translate(SUPERSCRIPT)} {label}"):
        st.markdown(escape_dollars(details))
        st.text(chunk_text)


def show_refusal(answer: Answer, trace: Trace) -> None:
    category = policy_category(trace) if answer.refusal_reason == "policy" else None
    suffix = f", category: {category}" if category else ""
    st.error(f"**Refused** (reason: {answer.refusal_reason}{suffix})")
    st.markdown(escape_dollars(answer.refusal_message or ""))


def show_sentences(answer: Answer) -> None:
    rendered = render_answer(answer)
    for s in rendered.sentences:
        note = " *(partially supported)*" if s.partial else ""
        st.markdown(f"{escape_dollars(s.text)} **{marker(s.numbers)}**{note}")
    if answer.partial_note:
        st.warning(f"Not found in the retrieved passages: {escape_dollars(answer.partial_note)}")
    st.caption("Citations")
    for c in rendered.citations:
        chunk = c.chunk
        item = f"Item {chunk.adv_item}: {chunk.item_title}" if chunk.adv_item else "unlabeled"
        details = (
            f"**Firm:** {chunk.firm_name}  \n**Item:** {item}  \n"
            f"**doc_type:** {chunk.doc_type}  \n**{c.pages.capitalize()}**  \n`{chunk.chunk_id}`"
        )
        show_citation(c.number, c.label, strip_header(chunk), details)


def show_answer(answer: Answer, trace: Trace) -> None:
    show_sub_queries(trace)
    if answer.refused:
        show_refusal(answer, trace)
    else:
        show_sentences(answer)
    removed = removed_with_reasons(answer)
    if removed:
        with st.expander(f"Removed by verifier ({len(removed)})"):
            for text, reason in removed:
                st.markdown(f"- ~~{text}~~  \n  *{reason}*")


def show_trace(trace: Trace) -> None:
    rows = trace_rows(trace)
    total_ms = sum(r.ms for r in rows) or 1.0
    st.subheader("Trace")
    table = [
        {
            "node": r.node,
            "ms": r.ms,
            "time": r.ms / total_ms,
            "in tokens": r.input_tokens,
            "out tokens": r.output_tokens,
            "cost ($)": r.cost_usd,
            "cached": "cached" if r.cached else "",
        }
        for r in rows
    ]
    st.dataframe(
        table,
        hide_index=True,
        column_config={
            "ms": st.column_config.NumberColumn(format="%.0f"),
            "time": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format=" "),
            "cost ($)": st.column_config.NumberColumn(format="%.5f"),
        },
    )
    tokens = sum(r.input_tokens + r.output_tokens for r in rows)
    cost = sum(r.cost_usd for r in rows)
    cached = sum(r.cached for r in rows)
    note = f" {cached} cached event(s) show the original call's values." if cached else ""
    st.caption(f"Total {total_ms:.0f} ms, {tokens} tokens, ${cost:.5f}.{note}")


def sidebar() -> tuple[str, bool, bool, bool]:
    defaults = Settings()
    with st.sidebar:
        st.header("Pipeline")
        mode = st.selectbox(
            "Retrieval mode", RETRIEVAL_MODES, index=RETRIEVAL_MODES.index(defaults.retrieval_mode)
        )
        verifier = st.toggle("Verifier", value=defaults.enable_verifier)
        decomposition = st.toggle("Query decomposition", value=defaults.enable_decomposition)
        guard = st.toggle("Policy guard", value=defaults.enable_policy_guard)
    return mode, verifier, decomposition, guard


def ask_tab(toggles: tuple[str, bool, bool, bool]) -> None:
    options = [demo_label(i) for i in range(len(DEMO_QUESTIONS))] + [CUSTOM]
    choice = st.selectbox("Demo question", options)
    if choice == CUSTOM:
        question = st.text_input("Question")
    else:
        question = DEMO_QUESTIONS[options.index(choice)]
        st.markdown(escape_dollars(question))
    if st.button("Ask", type="primary", disabled=not question.strip()):
        load_base()
        with st.spinner("Running pipeline..."):
            answer, trace = pipeline_for(*toggles).run(question.strip())
        show_answer(answer, trace)
        show_trace(trace)


def main() -> None:
    st.set_page_config(page_title="AgentGuard", layout="wide")
    st.title("AgentGuard")
    st.caption("Verified research assistant over SEC Form ADV Part 2A brochures.")
    toggles = sidebar()
    ask, evals = st.tabs(["Ask", "Evals"])
    with ask:
        ask_tab(toggles)
    with evals:
        render_evals()


main()
