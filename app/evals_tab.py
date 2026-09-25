"""Evals tab: shows finished eval results from eval/results. It never runs or recomputes an eval."""

import sys

import altair as alt
import streamlit as st

from agentguard.config import PROJECT_ROOT, Settings

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # the repo-root `eval` package is not installed

from eval.records import RunResult
from eval.view import (
    DEV_ORDER,
    Card,
    chart_rows,
    dev_table,
    dev_variants,
    failing_rows,
    headline_cards,
    load_runs,
    probe_summary,
)

HEADLINE_CAPTION = (
    "The test split is held out: it was run once, with no tuning afterwards. The sample is "
    "small (8 questions: 4 answerable, 3 unanswerable, 1 policy), so one question moves "
    "correctness by 12.5 points overall. Read differences as anecdotes, not statistics."
)
DEV_CAPTION = "Dev was used for tuning prompts and settings, so these numbers are in-sample."
PROBE_CAPTION = (
    "A regression check that the policy prompt was written against, not an accuracy estimate."
)


@st.cache_data(show_spinner=False)
def _runs(signature: tuple[float, int]) -> dict[tuple[str, str], RunResult]:
    del signature  # only the cache key: it changes when a results file is added or rewritten
    return load_runs(Settings().results_dir)


def _signature() -> tuple[float, int]:
    files = list(Settings().results_dir.rglob("*.json"))
    return (max((f.stat().st_mtime for f in files), default=0.0), len(files))


def _card(col: st.delta_generator.DeltaGenerator, card: Card) -> None:
    with col:
        st.metric(f"{card.label} ({card.n})", card.value, card.delta, delta_color=card.color)
        st.caption(f"baseline {card.baseline}")


def show_headline(runs: dict[tuple[str, str], RunResult]) -> None:
    st.subheader("Test split: baseline vs full")
    cards = headline_cards(runs)
    if not cards:
        st.info("No test-split runs for both baseline and full in eval/results.")
        return
    st.caption("Each card shows the `full` value; the delta is against `baseline`.")
    for start in range(0, len(cards), 4):
        cols = st.columns(4)
        for col, card in zip(cols, cards[start : start + 4], strict=False):
            _card(col, card)
    st.caption(HEADLINE_CAPTION)


def show_dev_table(runs: dict[tuple[str, str], RunResult]) -> None:
    st.subheader("Dev split: every variant")
    variants = dev_variants(runs)
    if not variants:
        st.info("No dev runs in eval/results.")
        return
    st.dataframe(dev_table(variants), hide_index=True, width="stretch")
    st.caption(DEV_CAPTION)


def show_chart(runs: dict[tuple[str, str], RunResult]) -> None:
    rows = chart_rows(dev_variants(runs))
    if not rows:
        return
    order = [r["variant"] for r in rows if r["measure"].startswith("Correct")]
    base = alt.Chart(alt.Data(values=rows)).encode(
        x=alt.X("variant:N", sort=order, title=None, axis=alt.Axis(labelAngle=-30)),
        y=alt.Y("value:Q", title=None),
    )
    panels = []
    for measure in ("Correctness (%)", "Cost per query (USD)"):
        bars = base.transform_filter(alt.datum.measure == measure).mark_bar()
        text = (
            base.transform_filter(alt.datum.measure == measure)
            .mark_text(dy=-6)
            .encode(text="label:N")
        )
        panels.append((bars + text).properties(title=measure, width=320, height=240))
    st.subheader("Correctness and cost per query (dev)")
    st.altair_chart(alt.hconcat(*panels), width="content")
    st.caption(DEV_CAPTION)


def show_probes() -> None:
    st.subheader("Policy probes")
    summary = probe_summary(Settings().results_dir)
    if summary is None:
        st.info("No probe results in eval/results/probes.")
        return
    left, right = st.columns(2)
    left.metric(
        f"Block rate (n={summary.n_blocked_expected} should be blocked)", summary.block_rate
    )
    right.metric(
        f"False-block rate (n={summary.n_allowed_expected} should be allowed)",
        summary.false_block_rate,
    )
    st.caption(PROBE_CAPTION)


def show_failures(runs: dict[tuple[str, str], RunResult]) -> None:
    st.subheader("Failures browser")
    left, right = st.columns(2)
    split = left.selectbox("Split", ["dev", "test"])
    names = [v for (s, v) in runs if s == split]
    if not names:
        st.info(f"No {split} runs.")
        return
    variant = right.selectbox("Variant", sorted(names, key=_variant_rank))
    rows = failing_rows(runs[(split, variant)])
    if not rows:
        st.success("No answerable question below 1.0 correctness or faithfulness.")
        return
    for row in rows:
        c = "n/a" if row.correctness is None else f"{row.correctness:.2f}"
        f = "n/a" if row.faithfulness is None else f"{row.faithfulness:.2f}"
        with st.expander(f"{row.id}: {row.question} (correctness {c}, faithfulness {f})"):
            st.markdown(f"**Answer:** {row.answer_text or '(refused)'}")
            st.markdown(
                "**Retrieved chunk ids:** " + ", ".join(f"`{i}`" for i in row.retrieved_chunk_ids)
            )
            for fact in row.fact_verdicts:
                mark = "present" if fact.present else "**MISSING**"
                st.markdown(f"- {mark}: {fact.key_fact}  \n  *{fact.reason}*")
            for s in row.sentence_verdicts:
                if s.verdict != "supported":
                    st.markdown(f"- sentence {s.verdict}: {s.sentence}  \n  *{s.reason}*")


def _variant_rank(name: str) -> tuple[int, str]:
    return (DEV_ORDER.index(name) if name in DEV_ORDER else len(DEV_ORDER), name)


def render() -> None:
    runs = _runs(_signature())
    show_headline(runs)
    show_dev_table(runs)
    show_chart(runs)
    show_probes()
    show_failures(runs)
