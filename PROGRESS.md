# Progress

| Milestone | Status |
|---|---|
| M0. Repo skeleton and tooling | DONE |
| M1. Data contracts, LLM wrapper, tracing | DONE |
| M2. Ingestion: parse and chunk | DONE |
| M3. Retrieval: dense, sparse, fusion, rerank | DONE |
| M4. Generator and baseline pipeline | TODO |
| M5. Golden dataset | TODO |
| M6. Eval harness and baseline numbers | TODO |
| M7. Verifier agent | TODO |
| M8. Policy guard | TODO |
| M9. Evidence threshold and final test-set run | TODO |
| M10. Streamlit UI: Ask tab | TODO |
| M11. Streamlit UI: Evals tab | TODO |
| M12. MCP server | TODO |
| M13. Demo hardening and code freeze | TODO |

---

## M0 details

**What was built:** `uv`-managed project with the full repo layout from PLAN.md
section 1 (empty `__init__.py`s in `ingest/`, `retrieval/`, `agents/`;
`.gitkeep` placeholders in non-package dirs that aren't gitignored).
`src/agentguard/config.py` with the `Settings` class (pydantic-settings, all
fields/defaults from the spec) and a per-model price table. `Makefile` with
`install`, `lint`, `test`, `test-int`, `check`, and `ingest`/`eval`/`app`/`mcp`
stubs that exit non-zero with a "not implemented until M<n>" message.
`pyproject.toml` registers the `integration` pytest marker; `make test` runs
`pytest -m "not integration"` so unit tests can't hit the network by
accident. `.env.example`, `.gitignore` (`.env`, `data/processed/`, `.cache/`,
`qdrant_data/`, tool caches), minimal `README.md`, empty `DECISIONS.md`.

**Test results:**
- `make check` → ruff check: all checks passed; ruff format --check: 14 files
  already formatted; pytest (unit): 1 passed.
- `make test-int` → 0 selected (no integration tests exist yet, expected).
- `make ingest` / `make eval` / `make app` / `make mcp` → each prints its
  "not implemented until M<n>" message and exits non-zero, verified manually.
- `uv run python -c "from agentguard.config import Settings; print(Settings())"`
  with a `.env` present → loads correctly, `anthropic_api_key` prints masked
  as `SecretStr('**********')`.

**Deferred:** Nothing deferred from M0's task list.

**Non-obvious decision:** `make` wasn't installed on the dev machine and
`choco install make` failed for lack of admin rights; installed via
`winget install --scope user ezwinports.make` instead. See DECISIONS.md.

---

## M1 details

**What was built:**
- `models.py`: the 8 contracts exactly as specified (`Chunk`, `RetrievedChunk`,
  `CitedSentence`, `VerificationResult`, `PolicyDecision`, `Answer`,
  `TraceEvent`, `Trace`). `Trace` has computed `total_ms`, `total_cost_usd`,
  `total_tokens`. `TraceEvent.started_at` is a `datetime`.
- `trace.py`: `trace_node(trace, name)` context manager. Yields a mutable
  `TraceEvent`, records wall-clock duration, appends the event even if the node
  raises.
- `llm.py`: `LLMClient.complete_structured(model, system, user, output_model,
  trace, node_name)`. Single tool forced via `tool_choice`; pydantic validation;
  one corrective retry with the validation error appended, then
  `StructuredOutputError`. `tenacity` exponential backoff on `RateLimitError` /
  `OverloadedError` only (SDK's own retries disabled). `diskcache` keyed on
  sha256 of (format version, model, system, user, schema, effective
  temperature, max_tokens). Cache entries store the result **and** the original
  call's input/output tokens, cost, and duration; a hit records 0 tokens/cost,
  `cached=True`, and `original_input_tokens`, `original_output_tokens`,
  `original_cost_usd`, `original_duration_ms` in `detail` (M6 reports these).
  `llm_temperature` is sent (via `extra_body`) only to models that accept it;
  see DECISIONS.md. Cost from the config price table; unknown model raises
  `UnknownModelPriceError`.
- `prompts/__init__.py`: `load_prompt(name)` reads `prompts/{name}.md`, error
  lists available prompts.
- `config.py`: `PROJECT_ROOT = Path(__file__).resolve().parents[2]`; all path
  fields and `env_file` absolute under it (relative overrides resolve against
  it, not cwd). Field constraints: top_k / top_n / rrf_k / max_tokens > 0,
  `verifier_max_drop_ratio` and `llm_temperature` in [0, 1], retry attempts
  >= 1, chunk sizes positive. Model validator: `chunk_overlap_tokens <
  chunk_target_tokens`. New fields: `enable_llm_cache`, `llm_temperature`
  (0.0), `llm_max_tokens` (2048), `llm_retry_attempts` (5). New constant
  `MODELS_WITHOUT_TEMPERATURE`. Sonnet 5 price corrected to $2/$10 (was $3/$15).

**Test results:**
- `make check` → ruff check: all checks passed; ruff format --check: 23 files
  already formatted; pytest (unit): 50 passed, 3 deselected. Includes: Settings
  loaded from a different cwd (paths absolute under PROJECT_ROOT, decoy cwd
  `.env` ignored), constraint and overlap-validator tests, cache-hit originals,
  temperature/max_tokens in cache key.
- `make test-int` → 3 passed:
  - tiny schema on `claude-sonnet-5`: `answer=42`, nonzero tokens and cost.
  - nested `$defs`/`$ref` schema (`list[CitedSentence]`) on `claude-sonnet-5`:
    accepted by the API, validated on the first attempt. Sample output:
    two sentences citing `acme-p7-0` and `acme-p9-1`; 890 in / 106 out
    tokens, $0.00284.
  - `claude-haiku-4-5-20251001` with `temperature=0.0` sent: accepted.

**Deferred:** Nothing. Requirement "pass temperature on every call" was changed
with Jasmeet's approval to "pass it to every model that accepts it"
(Sonnet 5 returns 400); see DECISIONS.md.

**Non-obvious decisions:** see DECISIONS.md (M1 entries).

---

## M2 details

**What was built:**
- Data prep (separate commit): the 10 brochures renamed to the approved slugs
  and committed (5.9 MB); `data/raw/firms.json` with name, lowercase aliases,
  doc_type, and Betterment's `wrap_appendix1_from_page: 35`.
- `models.py`: `DocType`, `FirmInfo`, `Page`; `Chunk.doc_type`, `Chunk.is_toc`.
- `ingest/parse.py`: `parse_pdf(path) -> list[Page]`. Same-row merging,
  paragraph breaks relative to the page's median line gap, header/footer
  stripping, NFKC and invisible-character cleanup, and the Gibbs glyph map
  with a per-document replacement count logged.
- `ingest/items.py`: canonical titles for part2a (1-19) and wrap_appendix1
  (1-9); `match_item_heading`, `match_title_heading`, `is_toc_page`,
  `is_part2b_cover`.
- `ingest/sections.py`: per-page doc_type (Part 2A / wrap appendix / Part 2B),
  heading candidates, longest increasing item sequence as boundaries, TOC run
  labeled Item 3, Part 2B kept unlabeled.
- `ingest/chunk.py`: sentence units, greedy packing near
  `chunk_target_tokens` with paragraph-preferred breaks, overlap, header line,
  stable chunk ids.
- `ingest/firms.py`, `ingest/pipeline.py` (`ingest_corpus`, `write_chunks`,
  per-doc item coverage), `cli.py` (`agentguard ingest` prints the summary
  table and exits 1 if any brochure is below its minimum). `make ingest` wired.

**Test results:**
- `make check` → ruff check and format clean; pytest (unit): 128 passed,
  3 deselected. New tests: 15 real "Item N" header variants plus 5 prose or
  wrong-title negatives; 8 real Fisher/Vanguard title-only headings plus 3
  body-text negatives; wrap appendix titles; real Atwood and Vanguard TOC pages
  detected, while Atwood p15 (5 real headings) is not; Part 2B cover vs prose;
  glyph map, NFKC, invisible characters; paragraph gaps; header/footer strip;
  chunk sizes within ±30% of target (5 seeds, on unit sums and rendered
  bodies); overlap, including the word-tail fallback; paragraph-preferred
  breaks; chunk_ids unique and stable; a real-corpus regression test (coverage
  minimums, ids and text identical across two runs, known facts in the right
  item, no Gibbs glyphs left).
- `agentguard ingest` → 745 chunks. Items detected: Atwood 18/18, Betterment
  part2a 18/18 and wrap_appendix1 8/9, Creative 16/18, Edelman 17/18, Facet
  18/18, Fisher 17/18, Gibbs 17/18, Savvy 18/18, Vanguard 16/18, Wealthfront
  18/18. All OK.
- Every miss is an item the brochure never labels: Item 1 (no "Item 1"
  heading) for Creative, Edelman, Fisher, Gibbs, Vanguard, and Betterment's
  appendix; Item 2 for Creative (a plain "Material Changes" heading in a doc
  that otherwise uses "Item N") and Vanguard (no heading at all). That text is
  kept with `adv_item=None`.
- 3 random chunks and 1 Fisher Item 5 chunk printed for review.

**Deferred:** Nothing.

**Non-obvious decisions:** see DECISIONS.md (M2 entries). Plan deviations:
doc_type on Chunk and per-doc_type acceptance thresholds, a `part2b` doc_type
for brochure supplements, and `Chunk.is_toc` (all approved by Jasmeet).

**Closing review (after Jasmeet's M2 decisions):** added `is_toc` (13 TOC
chunks, at least one per firm, all Item 3) with tests at the section, chunk,
and corpus level. File sizes in `src/agentguard/ingest/`: chunk.py 185,
firms.py 31, items.py 166, parse.py 149, pipeline.py 103, sections.py 189
(limit ~250). Longest function: `chunk_sections` at 34 lines (limit ~50).

---

## M3 details

**What was built:**
- `retrieval/dense.py`: `Embedder` (bge-small-en-v1.5, normalized, with bge's query
  prefix from the new config field `embedding_query_prefix`), a local on-disk Qdrant
  collection (cosine), and `DenseSearcher` with a `doc_id` payload filter.
- `retrieval/sparse.py`: regex tokenizer (keeps "1.25%" and "1,000,000"), BM25Okapi
  over a pickled tokenized corpus, and a firm filter applied before top-k.
- `retrieval/fusion.py`: `rrf_fuse`, a pure function using `math.fsum`, with
  deterministic ties (best rank, then chunk_id).
- `retrieval/rerank.py`: `Reranker` (CrossEncoder returning raw logits, one batched
  `predict()` per candidate group) and `rerank()`.
- `retrieval/retriever.py`: `Retriever` composes the stages by mode. It applies the
  firm filter (word-boundary alias match, `ingest/firms.py:match_firms`). A
  multi-firm query gets per-firm candidate retrieval with `top_k` split between
  firms, and the final `rerank_top_n` is split round-robin across firms. The
  reranker loads lazily. One `retrieve` trace event holds mode, firm_filter,
  per-stage counts and ms, and returned_per_firm.
- `ingest/index.py`: builds both indexes and excludes `is_toc` chunks, logged per
  firm. It deletes the Qdrant directory before a rebuild (a qdrant-client
  Windows bug kept deleted points) and checks the point count. `agentguard ingest`
  now builds the indexes; `agentguard search "q" --mode ...` prints ranked chunks
  with all scores.
- M2 fix: Part 2A Item 19 ends at its first standalone heading. Vanguard's
  "Investment risks" appendix (7 chunks) was mislabeled Item 19 and is now
  unlabeled. Corpus: 746 chunks, 733 indexed, 13 TOC excluded (1 per firm;
  Betterment, Creative Planning and Edelman have 2 each).
- Config (approved by Jasmeet): `reranker_model` is
  `cross-encoder/ms-marco-MiniLM-L-6-v2`; `rerank_score` is a raw logit. The
  `retrieval_mode` default was `hybrid` at the M3 commit; after M3, Jasmeet set it
  back to `hybrid_rerank` (see DECISIONS.md "After M3").

**Models:** first-run download to `C:\Users\HTC\.cache\huggingface\hub`:
bge-small-en-v1.5 133 MB and bge-reranker-base 1.13 GB (evaluated, no longer the
default), then ms-marco-MiniLM-L-6-v2 88 MB. Indexing 733 chunks with bge-small
takes 2-4 min on this CPU.

**Test results:**
- `make check` → ruff check and format clean; pytest (unit): 171 passed, 3
  deselected. New tests cover:
  - RRF: formula, order, tie-breaks, order independence, and bad input.
  - Retriever modes with mocked backends: dense-only, hybrid without rerank,
    rerank reordering, default mode from settings, and the trace contents.
  - Firm filtering: a single firm reaches both backends; aliases match on word
    boundaries only.
  - Multi-firm split: 3 + 3 for two firms in all three modes, 2 + 2 + 2 for
    three firms, and backfill when a firm runs out.
  - Real-backend behavior: stale index errors; BM25 filters before top-k and
    drops TOC and zero-score chunks; Qdrant filtering and rebuild/reset.
  - `match_firms` on real firms.json: all 6 manual queries plus negatives like
    "fishermen" and "unsavvy".
  - Item 19 cut: section-level and real-corpus regression tests.
- **Manual, `hybrid` mode, top result** (6 queries given by Jasmeet):

  | Query | Top result | Grade |
  |---|---|---|
  | What fees does Fisher Investments charge? | fisher p21-1, Item 18 (privacy); no Item 5 chunk in the top 6 | FAIL |
  | Has Vanguard been subject to any SEC enforcement action? | vanguard p19-2, Item 9 (SEC settlement) | PASS |
  | What are the fees for Betterment's wrap fee program? | betterment p10-1, part2a Item 5; wrap appendix Item 4 is #2 | FAIL (expected the wrap_appendix1 half) |
  | Compare Wealthfront and Betterment advisory fees | wealthfront p11-1, Item 5; 3 Wealthfront + 3 Betterment (wrap Item 4 x2, Item 9) | PASS |
  | Does Gibbs Wealth Management have custody of client assets? | gibbs p29-0, Item 15 (glyph-repaired text) | PASS |
  | Which firms charge a flat annual fee instead of a percentage of assets? | Savvy, Creative, Edelman, Wealthfront | FAIL; known limitation, below |

  Fisher hypothesis (not investigated in M3): once the filter is on, the firm
  name in the query carries no information but still boosts chunks that repeat
  "Fisher Investments" (the Item 18 privacy chunk is #1 in both dense and BM25).
  `hybrid_rerank` with MiniLM does put Fisher Item 5 first, at 1.8 s.
- **Latency (`hybrid`, 20 warm runs per query):** median 35 ms, max 81 ms
  (target < 1.5 s): PASS. The two-firm query is slowest (two filtered searches).
  `hybrid_rerank` with MiniLM: median 2.1 s, max 2.7 s; with bge-reranker-base:
  13.0 s median.
- **Cold start (`hybrid`):** 14.0 s = imports (torch / sentence-transformers)
  12.5 s + loading the embedder, Qdrant and BM25 1.4 s; the first query is then
  fast. `hybrid_rerank` adds about 5 s for the reranker load on its first query.
- Torch uses 6 threads (= `os.cpu_count()`). Each candidate group is scored in
  one batched `predict()` call.

**Known limitation (Jasmeet's grading):** cross-firm semantic queries. "Which
firms charge a flat annual fee instead of a percentage of assets?" should
surface Facet and Atwood, the flat-fee firms. No mode returns either one
(dense, hybrid, and both rerankers return Edelman, Savvy, Creative Planning and
Wealthfront). Without a firm filter, 6 slots over 733 chunks rank chunks that
mention "annual fee" and "flat fee" in passing, not firms whose fee model is
flat. Not addressed in M3.

**Deferred:** Nothing from M3's task list. Retrieval quality on Fisher, the
Betterment wrap appendix, and cross-firm questions is left to M6 to measure.

**Non-obvious decisions:** see DECISIONS.md (M3 entries).

---

## Notes for later milestones

- **Default retrieval (decided after M3):** `retrieval_mode = "hybrid_rerank"`
  with the MiniLM reranker, about 2.1 s warm on this CPU.
- **M4 integration questions (Jasmeet):**
  - Answerable: "What is Savvy's minimum account size?"; "What fees does Fisher
    Investments charge?"; "Has Vanguard been subject to any SEC enforcement action?"
  - Refusal: "What is Savvy's CEO's favorite restaurant?"
- **M6:** `baseline` = `hybrid_rerank` (PLAN.md, unchanged). `dense_only` and
  `hybrid` are the ablation variants.
- **M9:** the evidence threshold uses the top `rerank_score` (raw MiniLM logit),
  as planned; tune `min_rerank_score` on dev.
- **M13 offline demo:** set `HF_HUB_OFFLINE=1` in the environment for the demo
  (Streamlit, the CLI, and the `--offline-demo` launch). Without it,
  sentence-transformers sends HTTP HEAD requests to the Hugging Face Hub on every
  model load, which slows cold start and can fail with the network off. Models are
  cached in `~/.cache/huggingface/hub` (bge-small 133 MB, MiniLM 88 MB). Verify
  with the network actually disconnected.
