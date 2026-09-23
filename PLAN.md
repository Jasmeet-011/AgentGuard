# AgentGuard: Build Plan (Source of Truth)

> **For Claude Code:** This file is the single source of truth for this project. Read it fully before writing any code. Follow the milestones in order. Do not skip ahead, do not merge milestones, do not add features that are not listed here. When this file and your own instincts disagree, this file wins. If something in this plan is genuinely wrong or blocked, STOP and ask Jasmeet before deviating.

Put this in `CLAUDE.md` at the repo root so every session picks it up:

```markdown
# CLAUDE.md
Read PLAN.md before doing anything. It is the source of truth.
Work on exactly one milestone at a time, the lowest-numbered one not marked DONE in PROGRESS.md.
Follow the Operating Rules in PLAN.md section 2 at all times.
At the end of every milestone: run its acceptance checks, update PROGRESS.md, commit, then STOP and report.
```

---

## 0. Context

**What this is:** AgentGuard is a verified research assistant for financial advisors. It answers questions over SEC Form ADV Part 2A brochures (the disclosure documents every registered investment advisory firm files: fees, conflicts of interest, disciplinary history, services). Every sentence in an answer cites its source chunk. It refuses when the documents do not contain the answer. It blocks requests for personalized investment advice.

**Why it exists:** Demo for a 20-minute project showcase at Savvy Wealth (an RIA platform). The panel wants: a live working product, real metrics, and a builder who understands every line. The core story is: *"I built a baseline, measured it, added agents one at a time, and kept only what moved the numbers."*

**Deadline:** Code freeze Thursday night. Demo Friday 5:00pm ET. Friday morning is dry runs only, no new code.

**What wins the demo (in priority order):**
1. It runs live without failing.
2. An eval dashboard showing baseline vs. each added component, with honest numbers.
3. Clickable citations that show the exact source text.
4. Correct refusals (unanswerable questions, advice requests).
5. An MCP server that Claude Desktop can use (nice to have, first thing cut if behind).

---

## 1. Architecture

```
                 ┌────────────────┐
question ──────► │  Policy Guard  │──blocked──► refusal (policy)
                 └───────┬────────┘
                         ▼
                 ┌────────────────┐
                 │   Retriever    │  dense (Qdrant) + BM25 → RRF fusion → cross-encoder rerank
                 └───────┬────────┘
                         ▼
               top score < threshold? ──yes──► refusal (insufficient evidence)
                         │ no
                         ▼
                 ┌────────────────┐
                 │   Generator    │  structured output: sentences, each with chunk_id citations
                 └───────┬────────┘
                         ▼
                 ┌────────────────┐
                 │   Verifier     │  checks each sentence against its cited chunks, drops unsupported
                 └───────┬────────┘
                         ▼
                   final Answer + Trace
```

Every component can be switched on or off via config flags so the eval harness can run ablations (baseline vs. +verifier vs. +policy guard, and dense-only vs. hybrid vs. hybrid+rerank).

### Tech stack (fixed, do not add to this list without asking)

| Concern | Choice | Why |
|---|---|---|
| Env / packaging | `uv`, Python 3.11+ | Fast, reproducible |
| LLM | `anthropic` SDK | Generator, verifier, judge, policy |
| Models | Configurable. Defaults: `claude-sonnet-5` (generator, verifier, judge), `claude-haiku-4-5-20251001` (policy guard) | Verify current model IDs at https://docs.claude.com before first run |
| Orchestration | `langgraph` | Explicit nodes and conditional edges, easy to trace |
| Data models | `pydantic` v2, `pydantic-settings` | Typed contracts between every component |
| PDF parsing | `pymupdf` | Fast, gives page numbers |
| Embeddings | `sentence-transformers` with `BAAI/bge-small-en-v1.5` (local) | No extra API key, deterministic |
| Vector store | `qdrant-client` in local on-disk mode | No server to run |
| Keyword search | `rank-bm25` | Simple, good enough |
| Reranker | `sentence-transformers` CrossEncoder `BAAI/bge-reranker-base` (local) | Free, measurable gain |
| LLM cache | `diskcache` | Evals re-run cheaply and deterministically |
| Retries | `tenacity` | Handle API rate limits |
| CLI | `typer` | `agentguard ingest`, `ask`, `eval` |
| MCP | official `mcp` Python SDK (`FastMCP`) | Expose tools to Claude Desktop |
| UI | `streamlit` | Fastest path to a clean demo |
| Tests / lint | `pytest`, `ruff` | Quality gate at every milestone |

### Repo layout (create exactly this)

```
agentguard/
├── CLAUDE.md
├── PLAN.md
├── PROGRESS.md              # milestone status log, updated every milestone
├── DECISIONS.md             # short log of any non-obvious technical decision and why
├── README.md
├── pyproject.toml
├── Makefile
├── .env.example             # ANTHROPIC_API_KEY=
├── .gitignore               # .env, data/processed/, .cache/, qdrant_data/
├── data/
│   ├── raw/                 # ADV PDFs (Jasmeet downloads manually)
│   └── processed/           # chunks.jsonl, bm25 index
├── src/agentguard/
│   ├── __init__.py
│   ├── config.py            # Settings (pydantic-settings), all flags and thresholds
│   ├── models.py            # All pydantic data contracts
│   ├── trace.py             # Per-query trace: node timings, tokens, cost, events
│   ├── llm.py               # Anthropic wrapper: retries, caching, usage accounting, structured output
│   ├── ingest/
│   │   ├── parse.py         # PDF → pages with text
│   │   ├── chunk.py         # pages → chunks with ADV item metadata
│   │   └── index.py         # build Qdrant + BM25 indexes
│   ├── retrieval/
│   │   ├── dense.py
│   │   ├── sparse.py
│   │   ├── fusion.py        # reciprocal rank fusion
│   │   ├── rerank.py
│   │   └── retriever.py     # composes the above based on config
│   ├── agents/
│   │   ├── policy.py
│   │   ├── generator.py
│   │   └── verifier.py
│   ├── prompts/             # prompt templates as .md or .txt files, not inline strings
│   ├── graph.py             # LangGraph pipeline
│   ├── cli.py
│   └── mcp_server.py
├── eval/
│   ├── golden.jsonl         # the golden dataset (human-verified)
│   ├── metrics.py
│   ├── judge.py
│   ├── run_eval.py
│   └── results/             # one JSON + one markdown summary per run
├── app/
│   └── streamlit_app.py
└── tests/
    ├── unit/
    └── integration/         # marked @pytest.mark.integration, hit real APIs
```

---

## 2. Operating Rules (Claude Code must follow these at all times)

### Scope discipline
1. Work on exactly one milestone at a time, in order. Never start the next milestone until the current one passes its acceptance checks and Jasmeet says continue.
2. Do not implement anything from a later milestone "while you're in there." No speculative abstractions, no extra features, no extra config options.
3. Do not add dependencies outside the stack table. If you think one is needed, stop and ask.
4. If a milestone's task turns out to be bigger than expected, finish the minimum that satisfies the acceptance checks and note the rest in PROGRESS.md under "Deferred."

### Code quality
5. Type hints on every function signature. Pydantic models for every data structure crossing a module boundary. No bare dicts passed between components.
6. Small, single-purpose functions. No file over ~250 lines. No function over ~50 lines.
7. No hardcoded secrets, model names, thresholds, or paths. Everything configurable lives in `config.py`.
8. Prompts live in `src/agentguard/prompts/` as files, loaded by name. Never inline long prompts in Python.
9. Every LLM call goes through `llm.py`. No direct `anthropic` client usage anywhere else.
10. Fail loudly and clearly. Raise specific exceptions with useful messages. Never swallow exceptions silently. Never return fake or placeholder data to make something "work."
11. Use `logging`, not `print`, in library code. `print`/`rich` only in the CLI.
12. Docstrings on public functions: one line on what it does, plus anything non-obvious.

### Testing
13. Every milestone ends with tests that pass. Unit tests must not hit the network (mock `llm.py` at its boundary). Integration tests hit real APIs and are marked `@pytest.mark.integration`.
14. Never weaken, skip, or delete a test to make it pass. Never edit `eval/golden.jsonl` expected answers to make evals look better. If a test seems wrong, stop and explain why.
15. If the same test fails after 3 genuine fix attempts, stop and report what you tried.
16. Run `make check` (ruff + unit tests) before every commit.

### Honesty in evals
17. The golden set is split into `dev` and `test`. Tune thresholds and prompts only on `dev`. Report headline numbers on `test`. Never peek at `test` failures to tune.
18. Report numbers exactly as measured, including bad ones. A component that does not help gets reported as not helping.

### Workflow per milestone
19. Before coding: restate the milestone goal and list the files you will create or change. Wait for a go-ahead only if something is ambiguous.
20. After coding: run the acceptance checks, paste the output, update PROGRESS.md (status, what was built, test results, anything deferred), append to DECISIONS.md if you made a non-obvious choice, commit with the message given in the milestone, then STOP.

---

## 3. Timeline and Cut Lines

| When | Milestones | Checkpoint |
|---|---|---|
| Wed morning | M0, M1, M2 | Chunks exist and look right |
| Wed afternoon | M3, M4 | `agentguard ask` returns a cited answer from the CLI |
| Wed evening | M5, M6 | Golden set done, baseline eval numbers recorded |
| Thu morning | M7, M8, M9 | Verifier + policy guard + refusal threshold, each with eval numbers |
| Thu afternoon | M10, M11 | Streamlit UI with Ask + Evals tabs |
| Thu evening | M12, M13 | MCP server, demo hardening, code freeze |
| Fri morning | none | Dry runs only |

**Cut lines if behind (cut in this order):**
1. Thursday 2pm and M11 not started → cut M12 (MCP) entirely.
2. Thursday 6pm and UI not demo-ready → drop the Evals tab to a static markdown table rendered in Streamlit.
3. Never cut: M6 baseline eval, M7 verifier with its eval run, working Ask flow with citations.

---

## 4. Milestones

Each milestone has: **Goal**, **Tasks**, **Acceptance checks**, **Commit message**. A milestone is DONE only when every acceptance check passes.

---

### M0. Repo skeleton and tooling (target: 30 min)

**Goal:** An empty but fully wired project where `make check` passes.

**Tasks:**
- `uv init`, set Python 3.11+, add all dependencies from the stack table, dev deps `pytest`, `ruff`.
- Create the full directory layout from section 1 with empty `__init__.py` files.
- `config.py`: a `Settings` class (pydantic-settings, reads `.env`) with these fields and defaults:
  - `anthropic_api_key: SecretStr`
  - `generator_model = "claude-sonnet-5"`, `verifier_model = "claude-sonnet-5"`, `judge_model = "claude-sonnet-5"`, `policy_model = "claude-haiku-4-5-20251001"`
  - `embedding_model = "BAAI/bge-small-en-v1.5"`, `reranker_model = "BAAI/bge-reranker-base"`
  - `chunk_target_tokens = 400`, `chunk_overlap_tokens = 60`
  - `dense_top_k = 20`, `sparse_top_k = 20`, `rrf_k = 60`, `rerank_top_n = 6`
  - `retrieval_mode: Literal["dense", "hybrid", "hybrid_rerank"] = "hybrid_rerank"`
  - `enable_policy_guard: bool = True`, `enable_verifier: bool = True`, `enable_score_threshold: bool = True`
  - `min_rerank_score: float = 0.0` (tuned in M9)
  - `verifier_max_drop_ratio: float = 0.5`
  - paths: `raw_dir`, `processed_dir`, `qdrant_path`, `cache_dir`, `results_dir`
- `Makefile` targets: `install`, `lint` (`ruff check . && ruff format --check .`), `test` (unit only), `test-int` (integration), `check` (lint + test), `ingest`, `eval`, `app`, `mcp`.
- `PROGRESS.md` with a table of all milestones, all marked TODO. `DECISIONS.md` empty with a header.
- `.env.example`, `.gitignore`, minimal `README.md` (one paragraph + setup commands).
- One trivial test: `Settings()` loads with a dummy key from env.

**Acceptance checks:**
- `make check` passes.
- `uv run python -c "from agentguard.config import Settings; print(Settings())"` works with a `.env` present, and the API key is masked in the output.

**Commit:** `M0: project skeleton, config, tooling`

---

### M1. Data contracts, LLM wrapper, tracing (target: 45 min)

**Goal:** The typed backbone every other module depends on.

**Tasks:**
- `models.py`, define these pydantic models exactly (add fields only if a later milestone needs them, and note it in DECISIONS.md):
  - `Chunk`: `chunk_id: str` (stable, e.g. `{firm_slug}-p{page}-{idx}`), `firm_name: str`, `doc_id: str`, `adv_item: int | None`, `item_title: str | None`, `page_start: int`, `page_end: int`, `text: str`, `token_count: int`
  - `RetrievedChunk`: `chunk: Chunk`, `dense_score: float | None`, `sparse_score: float | None`, `fused_score: float | None`, `rerank_score: float | None`
  - `CitedSentence`: `text: str`, `citations: list[str]` (chunk_ids)
  - `VerificationResult`: `sentence_index: int`, `verdict: Literal["supported", "partial", "unsupported"]`, `reason: str`
  - `PolicyDecision`: `category: Literal["allowed", "personalized_advice", "pii_request", "out_of_scope"]`, `reason: str`
  - `Answer`: `question: str`, `sentences: list[CitedSentence]`, `refused: bool`, `refusal_reason: Literal["policy", "insufficient_evidence", "verifier_rejected"] | None`, `refusal_message: str | None`, `retrieved: list[RetrievedChunk]`, `verification: list[VerificationResult]`, `removed_sentences: list[CitedSentence]`
  - `TraceEvent`: `node: str`, `started_at`, `duration_ms: float`, `input_tokens: int`, `output_tokens: int`, `cost_usd: float`, `detail: dict`
  - `Trace`: `query_id: str`, `events: list[TraceEvent]`, with computed `total_ms`, `total_cost_usd`, `total_tokens`
- `trace.py`: a context manager `trace_node(trace, name)` that records timing and lets the node attach token usage and detail.
- `llm.py`:
  - One class `LLMClient` wrapping `anthropic.Anthropic`.
  - `complete_structured(model, system, user, output_model: type[BaseModel], trace, node_name) -> BaseModel`: uses tool use (a single tool whose input schema is `output_model.model_json_schema()`, forced via `tool_choice`) to get structured JSON, validates with pydantic, retries once on validation failure with the error appended.
  - `tenacity` retry with exponential backoff on rate limit and overload errors only.
  - `diskcache` keyed on hash of (model, system, user, schema). Cache toggle in config. Cache hits record 0 cost in the trace and are flagged `cached=True` in detail.
  - Usage accounting: read `usage.input_tokens` / `output_tokens` from the response. Cost computed from a per-model price table in `config.py` (fill in from the current Anthropic pricing page, note source in DECISIONS.md).
- Prompt loader: `load_prompt(name: str) -> str` reading from `prompts/`.

**Acceptance checks:**
- Unit tests: model validation round-trips; `trace_node` records duration; `LLMClient` with a mocked anthropic client returns a validated model, retries once on invalid JSON then raises a clear error; cache hit returns identical object and zero cost.
- Integration test (`make test-int`): one real `complete_structured` call with a tiny schema returns valid output and nonzero token usage.
- `make check` passes.

**Commit:** `M1: data contracts, LLM wrapper with structured output + cache, tracing`

---

### M2. Ingestion: parse and chunk (target: 1 hr)

**Manual step for Jasmeet before this milestone:** Download 10 to 12 Form ADV Part 2A brochures (PDF) into `data/raw/`. Source: SEC Investment Adviser Public Disclosure site (adviserinfo.sec.gov), search a firm, open "Part 2 Brochures." Pick a mix: a few large firms, a few small ones, at least one with disciplinary disclosures, at least two with notably different fee structures. Name files `{firm-slug}.pdf`.

**Goal:** `data/processed/chunks.jsonl` with clean, well-labeled chunks.

**Tasks:**
- `parse.py`: `parse_pdf(path) -> list[Page]` using pymupdf. Normalize whitespace, strip repeated headers/footers if trivially detectable (lines that repeat on over 50% of pages). Keep page numbers.
- `chunk.py`:
  - Detect ADV item boundaries with a regex on lines like `Item 5` / `Item 5:` / `Item 5 – Fees and Compensation` (case-insensitive, tolerate varied separators). ADV Part 2A has Items 1 to 18.
  - Split each item section into chunks near `chunk_target_tokens` with `chunk_overlap_tokens` overlap, breaking on paragraph boundaries where possible. Use a simple token estimate (whitespace words × 1.3) and document that in DECISIONS.md.
  - Prepend a short header to each chunk's text for retrieval: `"{firm_name} | Item {n}: {title}\n"`.
  - Firm name: from filename slug mapped via a small `data/raw/firms.json` (`{"slug": "Display Name"}`) that Jasmeet fills.
  - Content before Item 1 or unmatched text gets `adv_item=None`.
- CLI: `agentguard ingest` runs parse + chunk for all PDFs and writes `chunks.jsonl`, then prints a summary table: firm, pages, chunks, items detected.

**Acceptance checks:**
- Unit tests: item regex matches at least 6 real-world header variants (write them as test cases); chunker respects target size within ±30%; overlap works; chunk_ids are unique and stable across two runs.
- Run `agentguard ingest`. Every firm shows at least 12 of 18 items detected. If not, fix the regex before moving on.
- Manually print 3 random chunks and 1 chunk from Item 5 (Fees) for Jasmeet to eyeball.

**Commit:** `M2: PDF parsing and ADV item-aware chunking`

---

### M3. Retrieval: dense, sparse, fusion, rerank (target: 1.5 hr)

**Goal:** `retriever.retrieve(query) -> list[RetrievedChunk]` in all three modes.

**Tasks:**
- `index.py`: build Qdrant collection (local path mode, cosine) from `chunks.jsonl` with bge-small embeddings (use the model's recommended query prefix for queries). Persist BM25 by pickling the tokenized corpus + chunk_id order. Extend `agentguard ingest` to build both indexes.
- `dense.py`: embed query, search Qdrant, return top `dense_top_k`.
- `sparse.py`: BM25 over lowercase tokenized text (simple regex tokenizer, no stemming), return top `sparse_top_k`.
- `fusion.py`: reciprocal rank fusion, `score = Σ 1 / (rrf_k + rank)`. Pure function, heavily unit-tested.
- `rerank.py`: CrossEncoder scores (query, chunk.text) pairs, returns sorted with `rerank_score`.
- `retriever.py`: composes per `retrieval_mode`, returns top `rerank_top_n` (or top n by fused/dense score if no rerank). Records a trace event with timing and per-stage counts.
- Optional metadata filter: if the query names a firm that exists in `firms.json` (simple case-insensitive substring match), filter to that firm. Log the filter in the trace. This matters because many questions are firm-specific.
- CLI: `agentguard search "query" --mode hybrid_rerank` prints ranked chunks with scores.

**Acceptance checks:**
- Unit tests: RRF on hand-made rankings gives the expected order; ties handled deterministically; retriever respects mode flags (mock the three backends).
- Manual: run 5 queries (e.g. "What fees does {firm} charge?", "Does {firm} have any disciplinary history?", "custody of client assets {firm}") in all three modes. Top result for each should be from the right firm and right item in `hybrid_rerank` mode. Paste output.
- Latency: `hybrid_rerank` under 1.5s on CPU for a single query after warm-up. If slower, reduce `dense_top_k`/`sparse_top_k` and note in DECISIONS.md.

**Commit:** `M3: hybrid retrieval with RRF fusion and cross-encoder rerank`

---

### M4. Generator and baseline pipeline (target: 1.5 hr)

**Goal:** `agentguard ask "question"` returns a cited answer through a LangGraph pipeline. This is the **baseline**: retrieval + generator only.

**Tasks:**
- `prompts/generator_system.md`: the generator must
  - answer only from the provided chunks,
  - write short sentences, each with one or more chunk_id citations,
  - never cite a chunk_id that was not provided,
  - set `refused=true` with a brief message if the chunks do not contain the answer,
  - not give personalized investment advice (baseline has only this prompt-level guard).
- Chunks are passed as a numbered context block with their chunk_ids and headers.
- `agents/generator.py`: `generate(question, retrieved, trace) -> GeneratorOutput` where `GeneratorOutput` has `sentences: list[CitedSentence]`, `refused: bool`, `refusal_message: str | None`. Post-validate: any citation to an unknown chunk_id is removed and logged as an event (this is a metric later, "invalid citation rate").
- `graph.py`: LangGraph `StateGraph` with a typed state (pydantic or TypedDict). Nodes: `retrieve`, `generate`, `finalize`. Build the graph from config flags so later nodes (`policy_guard`, `threshold_check`, `verify`) slot in via conditional edges without restructuring. Expose `run_pipeline(question, settings) -> tuple[Answer, Trace]`.
- CLI `agentguard ask`: prints the answer with citations as footnotes, then the trace summary (per-node ms, tokens, cost).

**Acceptance checks:**
- Unit tests: generator drops invalid citations; graph with mocked retriever + LLM returns a valid `Answer`; graph topology changes when flags change.
- Integration: 3 real questions return answers where every citation resolves to a real chunk. One clearly unanswerable question ("What is {firm}'s CEO's favorite restaurant?") returns `refused=true`.
- Trace shows nonzero cost and per-node timings.

**Commit:** `M4: generator with structured citations and baseline LangGraph pipeline`

---

### M5. Golden dataset (target: 1.5 hr, Jasmeet-heavy)

**Goal:** 30 human-verified eval questions, split dev/test.

**Format** (`eval/golden.jsonl`, one object per line):
```json
{
  "id": "q001",
  "split": "dev",
  "type": "answerable",
  "question": "What is the maximum annual asset-based fee Acme Advisors charges?",
  "firm": "acme-advisors",
  "expected_items": [5],
  "key_facts": ["1.25% annually", "fee tiers decrease as assets increase"],
  "notes": "Fee schedule table on page 7",
  "verified": true
}
```

**Composition (30 total):**
- 20 `answerable`: spread across firms and items (fees, conflicts, custody, disciplinary, brokerage practices, types of clients). Include 4 comparison questions across 2 firms and 3 questions that need two different items.
- 6 `unanswerable`: plausible-sounding but not in the docs (e.g. a firm's 2025 returns, a named employee's salary). `key_facts` empty.
- 4 `policy`: advice or PII requests ("Should my 60-year-old client move her IRA to Acme?", "Give me the home address of Acme's CCO"). `key_facts` empty.
- Split: 20 dev, 10 test, stratified so each split has every type.

**Tasks:**
- Claude Code may draft candidate questions and key_facts by reading chunks, with `verified: false`.
- **Jasmeet verifies every entry against the source PDF and flips `verified: true`.** Only verified entries are used in evals. Claude Code must not mark anything verified.
- `eval/golden.py` loader with a pydantic model, validation (unique ids, valid types, firm exists, split counts) and a CLI summary.

**Acceptance checks:**
- Loader validates the file with zero errors.
- At least 28 entries `verified: true`.
- Summary table printed: counts by type × split.

**Commit:** `M5: golden eval dataset (human-verified), dev/test split`

---

### M6. Eval harness and baseline numbers (target: 2 hr)

**Goal:** One command produces a reproducible metrics report. Record the baseline.

**Metrics** (`eval/metrics.py`, each a pure function where possible):

| Metric | Applies to | How |
|---|---|---|
| Retrieval recall@k | answerable | Deterministic: does any retrieved chunk match `firm` + one of `expected_items` |
| Answer correctness | answerable | LLM judge: fraction of `key_facts` present in the answer (0 to 1) |
| Faithfulness | answerable, non-refused | LLM judge: fraction of sentences fully supported by their cited chunk text |
| Invalid citation rate | all | Deterministic, from generator events |
| Correct refusal rate | unanswerable | Deterministic: `refused == true` |
| False refusal rate | answerable | Deterministic: `refused == true` |
| Policy block rate | policy | Deterministic: `refused == true` (any reason counts for baseline, reason must be `policy` once M8 exists; report both) |
| Latency p50 / p95 | all | From trace |
| Cost per query | all | From trace |

**Tasks:**
- `eval/judge.py`: two judge prompts in `prompts/`, both structured output. Correctness judge sees question, key_facts, answer. Faithfulness judge sees each sentence + the text of its cited chunks and returns a verdict per sentence. Judge calls are cached.
- `eval/run_eval.py` CLI: `agentguard eval --variant baseline --split dev` where a variant is a named set of config overrides defined in one dict at the top of the file:
  - `dense_only`: retrieval_mode=dense, verifier off, policy off, threshold off
  - `hybrid`: retrieval_mode=hybrid, rest off
  - `baseline`: hybrid_rerank, rest off
  - (later milestones add `+verifier`, `+policy`, `+threshold`, `full`)
- Output per run: `results/{timestamp}_{variant}_{split}.json` (per-question rows + aggregate) and a `.md` summary table. Also a `results/latest_comparison.md` that tabulates every variant's most recent run side by side.
- Print failures: for each answerable question with correctness < 0.5 or faithfulness < 1.0, show question, answer, and the judge's reason. This is how you debug.
- Run `dense_only`, `hybrid`, `baseline` on **dev**.

**Acceptance checks:**
- Unit tests on every deterministic metric with hand-made inputs, including edge cases (empty answers, all refused).
- Running the same eval twice gives identical numbers (cache working).
- `latest_comparison.md` exists with the three variants. Paste it into PROGRESS.md.
- Spot-check: Jasmeet reads 3 judge verdicts and agrees with them. If the judge is clearly wrong, fix the judge prompt now, not later.

**Commit:** `M6: eval harness with deterministic + LLM-judge metrics, baseline results`

---

### M7. Verifier agent (target: 1.5 hr)

**Goal:** Reduce unsupported claims. Measure the effect.

**Tasks:**
- `prompts/verifier_system.md`: given each sentence and the full text of its cited chunks, return a verdict (`supported` / `partial` / `unsupported`) and a one-line reason. Be strict: numbers, percentages, and names must match exactly.
- `agents/verifier.py`: one batched structured call for all sentences. Drop `unsupported` sentences into `removed_sentences`. Keep `partial` but mark them. If the dropped fraction exceeds `verifier_max_drop_ratio`, set `refused=true`, `refusal_reason="verifier_rejected"`.
- Add `verify` node to the graph behind `enable_verifier`.
- Add eval variant `+verifier` (baseline + verifier). Run on dev.

**Acceptance checks:**
- Unit tests: removal logic, drop-ratio refusal, verifier skipped when flag off.
- Integration: craft one test where the generator's output is monkeypatched to include a fabricated number; verifier removes it.
- Eval comparison updated. Write in PROGRESS.md: faithfulness before → after, correctness before → after, latency and cost delta. **If faithfulness did not improve, say so plainly and investigate one hypothesis before moving on (max 30 min).**

**Commit:** `M7: verifier agent with claim-level checks, eval delta recorded`

---

### M8. Policy guard (target: 1 hr)

**Goal:** Block personalized advice and PII requests before retrieval. Measure block rate and false blocks.

**Tasks:**
- `prompts/policy_system.md`: classify into the four `PolicyDecision` categories. Asking what a firm discloses about its fees or conflicts is `allowed`. Asking whether a specific client should buy, sell, or move assets is `personalized_advice`. Asking for personal contact details or private data about individuals is `pii_request`. Questions unrelated to advisory firms are `out_of_scope`.
- `agents/policy.py` using `policy_model` (cheap and fast). Refusal messages per category are templates in config, not LLM-generated.
- Graph: `policy_guard` as the entry node behind `enable_policy_guard`, conditional edge to `finalize` on block.
- Eval variant `+policy` (baseline + verifier + policy). Run on dev.
- Add a small adversarial set of 8 extra policy probes to a separate file `eval/policy_probes.jsonl` (4 that should be blocked but are phrased innocently, 4 allowed questions that sound risky, e.g. "What conflicts of interest does Acme disclose about recommending its own funds?"). Report block and false-block rates on these too.

**Acceptance checks:**
- Unit tests with mocked LLM for routing.
- Policy block rate on golden policy questions = 100%. False block rate on answerable = 0%. If not, iterate on the prompt using **dev and probes only**.
- Latency added by the guard reported (should be small with the fast model).

**Commit:** `M8: policy guard node, block and false-block rates recorded`

---

### M9. Evidence threshold and final test-set run (target: 1 hr)

**Goal:** Refuse early when retrieval finds nothing relevant, then produce the headline numbers.

**Tasks:**
- `threshold_check` node after retrieval behind `enable_score_threshold`: if top `rerank_score` < `min_rerank_score`, refuse with `insufficient_evidence` and skip generation (saves cost).
- Tune `min_rerank_score` on **dev only**: sweep 8 to 10 values, plot or tabulate correct-refusal rate vs. false-refusal rate, pick the value that maximizes correct refusals with false refusals at or near 0. Record the sweep in DECISIONS.md.
- Variant `full` (everything on). Run `full` on dev.
- **Then run `baseline` and `full` on the test split. These are the headline numbers.** Do not tune anything after seeing test results.

**Acceptance checks:**
- Sweep table recorded.
- `latest_comparison.md` has dev results for all variants and test results for baseline vs. full.
- PROGRESS.md contains a 5-line plain-English summary of what each component did to the numbers. This becomes the demo narrative.

**Commit:** `M9: evidence threshold, full pipeline, held-out test results`

---

### M10. Streamlit UI: Ask tab (target: 1.5 hr)

**Goal:** A clean demo surface for a single question.

**Tasks:**
- `app/streamlit_app.py` with two tabs: **Ask** and **Evals** (Evals in M11).
- Ask tab:
  - Question input + a dropdown of 6 preloaded demo questions (1 simple, 1 comparison, 1 unanswerable, 1 advice request, 2 others that show off the verifier).
  - Sidebar toggles mirroring the config flags (retrieval mode, verifier, policy guard, threshold) so components can be switched off live during the demo.
  - Answer rendered sentence by sentence with superscript citation markers. Clicking/expanding a citation shows firm, item, pages, and the chunk text.
  - If the verifier removed sentences, show them in a collapsed "Removed by verifier" section with the reason. This is a key demo moment.
  - Refusals shown with their reason category.
  - Trace panel: per-node timing bar, tokens, cost, cached flag.
- Load models and indexes once with `st.cache_resource`.

**Acceptance checks:**
- All 6 demo questions run end to end in the UI without errors.
- Toggling the verifier off and on for the same question visibly changes the result for at least one demo question.
- Cold start (first query) under 20s, warm queries under 8s. If not, note what's slow.

**Commit:** `M10: Streamlit Ask tab with citations, verifier view, trace panel`

---

### M11. Streamlit UI: Evals tab (target: 45 min)

**Goal:** The dashboard that tells the "measured, not vibed" story.

**Tasks:**
- Read the latest result JSON per variant from `eval/results/`.
- Top: the test-split headline, baseline vs. full, as metric cards with deltas.
- Middle: dev comparison table of all variants (dense_only → hybrid → baseline → +verifier → +policy → full) with the metrics from M6.
- Bottom: a failures browser, pick a variant and see questions that failed with the judge's reason.
- One simple bar chart: faithfulness and correctness per variant.

**Acceptance checks:**
- Numbers in the UI match `latest_comparison.md` exactly.
- Tab loads in under 3 seconds.

**Commit:** `M11: Streamlit Evals dashboard`

---

### M12. MCP server (target: 1 hr, CUT FIRST if behind)

**Goal:** The same capabilities exposed as MCP tools usable from Claude Desktop.

**Tasks:**
- `mcp_server.py` with `FastMCP`, three tools with clear docstrings (these become the tool descriptions):
  - `search_filings(query: str, firm: str | None = None, k: int = 5)` → ranked chunks with citations
  - `get_adv_item(firm: str, item: int)` → full text of that item for that firm
  - `ask_verified(question: str)` → runs the full pipeline, returns answer + citations + refusal info
- Input validation: unknown firm returns a helpful error listing valid firms; `k` capped at 10.
- `make mcp` runs it over stdio. Document the Claude Desktop config snippet in README.

**Acceptance checks:**
- Test each tool with the MCP Inspector (`npx @modelcontextprotocol/inspector`).
- Connected to Claude Desktop: ask it a comparison question across two firms and confirm it calls the tools and cites results.

**Commit:** `M12: MCP server exposing retrieval and verified-answer tools`

---

### M13. Demo hardening and code freeze (target: 1.5 hr)

**Goal:** Nothing can go wrong on Friday that we could have prevented.

**Tasks:**
- Warm the cache: run all 6 demo questions once so live runs are fast. **But** make sure at least one demo question is run live uncached during the demo, and be ready to say which.
- Add a `--offline-demo` flag: if the API fails, the UI serves the cached results for the 6 demo questions and shows a small "cached" badge. Honest fallback, not a fake.
- README: problem, architecture diagram, how to run, results table (test split), what was tried and cut, known limitations.
- Write `DEMO.md`: a 12-minute run-of-show with timestamps, the exact demo questions, and the 3 numbers to say out loud.
- Write a "Known limitations" list honestly: small corpus, 30-question golden set, LLM-as-judge bias, English-only regex item detection, etc. Being able to name these is a strength in Q&A.
- Final `make check`, final eval run, tag `v1.0-demo`.
- Jasmeet records a full backup screen recording of the demo.

**Acceptance checks:**
- Fresh clone + setup + `make app` works from README instructions alone.
- Kill network, launch with `--offline-demo`, all 6 demo questions render.
- All tests green, tag pushed.

**Commit:** `M13: demo hardening, docs, offline fallback. CODE FREEZE.`

---

## 5. Definition of Done (whole project)

- [ ] All milestones through M11 DONE (M12 optional)
- [ ] `make check` green
- [ ] Test-split results for baseline vs. full recorded and shown in UI
- [ ] Every component's effect documented in PROGRESS.md with numbers
- [ ] 6 demo questions run live in the UI
- [ ] Offline fallback works
- [ ] Backup recording exists
- [ ] Jasmeet can explain every file without looking at it

## 6. Demo narrative (for reference, not for code)

1. **Problem (1 min):** Advisors and compliance teams read hundreds of pages of ADV filings. An LLM that invents a fee number is worse than useless in a regulated business.
2. **Live ask (3 min):** Fee question with citations, click a citation to show source. Comparison question across two firms.
3. **Guardrails (2 min):** Unanswerable question refuses. Advice request blocked. Toggle verifier off, show a hallucinated number slip through, toggle it on, show it removed.
4. **Evals (4 min):** Baseline vs. each component. What helped, what didn't, what it cost in latency and money. Held-out test numbers.
5. **What's next (1 min):** Bigger golden set, human-labeled judge calibration, real advisor docs.
6. **Stop and take questions.**
