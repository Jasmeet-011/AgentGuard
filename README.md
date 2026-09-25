# AgentGuard

A verified research assistant for financial advisors. It answers questions over SEC Form ADV Part 2A
brochures, cites every sentence to its source chunk, refuses when the documents do not contain the
answer, and blocks requests for personalized investment advice or personal information.

## Problem

Advisors and compliance teams read hundreds of pages of ADV filings (fees, conflicts, disciplinary
history). An LLM that invents a fee number is worse than useless in a regulated business. The design
question was not "can an LLM answer this" but "how do we know it is right, and what does each safety
component actually buy". So the project builds a baseline, measures it, adds one component at a
time, and reports what moved the numbers, including the components that did not.

The corpus is 10 brochures (Atwood, Betterment, Creative Planning, Edelman, Facet, Fisher, Gibbs,
Savvy, Vanguard Personal Advisor, Wealthfront): 746 chunks, each labelled with its ADV item and page.

## Architecture

```
question
   |
   v
Policy guard (Haiku) --blocked--> refusal (policy: personalized_advice | pii_request | out_of_scope)
   | allowed
   v
Decompose (Haiku): split multi-part questions into 1-3 sub-queries
   |
   v
Retrieve: dense (bge-small, Qdrant) + BM25 -> RRF fusion -> cross-encoder rerank (MiniLM)
          firm filter from the question; one retrieval per sub-query, merged
   |
   v
Generate (Sonnet): structured output, every sentence cites chunk_ids; refuses if nothing relevant
   |
   v
Verify (Sonnet, optional): checks each sentence against its cited chunks, drops unsupported ones
   |
   v
Answer + Trace (per-node time, tokens, cost)
```

Every component is a config flag (`src/agentguard/config.py`), so the eval harness can run
ablations, and the UI can switch them live. LLM calls are cached on disk, so evals and demos
re-run cheaply and identically.

## How to run

```
uv sync
cp .env.example .env     # fill in ANTHROPIC_API_KEY
make ingest              # parse PDFs, chunk, build the Qdrant and BM25 indexes (2-4 min on CPU)
make check               # ruff + unit tests
make app                 # Streamlit UI: Ask tab and Evals tab
make demo                # same, with HF_HUB_OFFLINE=1 (no Hugging Face lookups on start)
uv run agentguard ask "What is Savvy's minimum account size?"
make eval                # re-run the dev eval for every variant (calls the API)
```

The first run downloads the two local models (about 220 MB) into the Hugging Face cache. The LLM
cache (`.cache/`) is not in git, so a fresh clone makes live API calls until it warms up.
`make demo` needs the models already downloaded.

## Results

Held-out **test split**, run once per variant with no tuning afterwards. 8 questions: 4 answerable,
3 unanswerable, 1 policy. Source: `eval/results/latest_comparison.md`.

| Metric | baseline | full |
|---|---|---|
| Retrieval recall@k (n=4) | 100.0% | 100.0% |
| Answer correctness (n=4) | 87.5% | 87.5% |
| Faithfulness (n=4) | 100.0% | 100.0% |
| Correct refusal (n=3) | 100.0% | 100.0% |
| False refusal (n=4) | 0.0% | 0.0% |
| Policy block, reason = policy (n=1) | 0.0% | 100.0% |
| Latency p50 | 5.0 s | 7.9 s |
| Cost per query | $0.0164 | $0.0192 |

`baseline` = hybrid retrieval + rerank + generator. `full` = baseline + policy guard + query
decomposition + verifier. On this data the guardrails add safety and traceability, not accuracy:
the answers and scores are identical, and the price is +57% latency and +17% cost. One question
(q015, a fee comparison whose Vanguard fee chunk was not retrieved) is the only miss in both.
With 4 answerable questions, one question moves correctness by 25 points; read this as anecdote.

Note: the `full` variant in the eval switches the verifier on. The app's default (`make app`) has
the verifier off; see below.

Dev split (14 questions, used for tuning, so in-sample): dense, hybrid and baseline retrieval are
indistinguishable (recall 87.5%, correctness 90%, faithfulness 100%); decomposition raises recall
and correctness to 100% by fixing one two-part question (q018); the policy guard raises the policy
block rate from 66.7% to 100% with no false blocks. All variants are in the Evals tab.

## What was tried and cut

- **bge-reranker-base:** evaluated first (PLAN.md's choice); median 13.0 s per query on this CPU.
  Replaced by `ms-marco-MiniLM-L-6-v2` (about 2 s). Reranking itself showed no measurable quality
  gain on the dev set; it stays as the default on a manual probe, not on a measured gain.
- **Verifier default off:** no measured effect on dev or test (faithfulness was already 100%, it
  removed nothing), for about +2.1 s and +$0.0065 per query. Kept as a toggle. It does catch a
  fabricated number injected in an integration test.
- **M9 evidence threshold:** skipped. Correct refusals were already 100% on dev with no threshold,
  so there was nothing to improve, and tuning a cutoff on 3 unanswerable questions would fit noise.
  The flag exists but the node is not implemented.
- **MCP server (M12):** cut for time. No `mcp_server.py`; `make mcp` is a stub that exits non-zero.
- **Golden set:** 22 questions, not the planned 30 (time).

## Known limitations

- **Small golden set:** 22 questions (dev 14, test 8), all verified by hand. One test question
  moves overall correctness 12.5 points; the policy result rests on a single question.
- **One cached run per variant.** Sonnet 5 rejects a temperature setting, so runs cannot be pinned
  to temperature 0. Numbers are reproducible only because LLM outputs are cached; a fresh run can
  differ. Run-to-run variance was not measured.
- **LLM judge from the same model family** as the generator (Sonnet 5). It can share the
  generator's blind spots and biases. Only a handful of verdicts were spot-checked by hand.
- **Recall metric is item-level.** It matches firm, document type and ADV item, not the page or
  chunk, so it called q015 a retrieval hit although the Vanguard fee chunk was not retrieved.
- **Cross-firm semantic retrieval is weak.** "Which firms charge a flat annual fee?" returns
  chunks that mention fees in passing rather than the flat-fee firms. Firm-specific and two-firm
  questions work; open-ended "which firms" questions do not.
- **Decomposition was validated on one dev question (q018)**, which also motivated it. No test
  question exercised it.
- **The policy guard read q022** (a CEO's salary, written as an unanswerable question) as a
  personal-information request. It is refused either way, but for a different reason.
- English-only, regex-based ADV item detection; 10 firms; tables in PDFs are flattened to text.
- The offline demo was checked with cached LLM responses and Hugging Face offline mode, with the
  network simulated as unreachable (a dead proxy), not with the adapter physically disabled.
