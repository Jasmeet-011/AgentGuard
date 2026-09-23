# Progress

| Milestone | Status |
|---|---|
| M0. Repo skeleton and tooling | DONE |
| M1. Data contracts, LLM wrapper, tracing | DONE |
| M2. Ingestion: parse and chunk | TODO |
| M3. Retrieval: dense, sparse, fusion, rerank | TODO |
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
  sha256 of (model, system, user, schema); hits record 0 tokens/cost and
  `cached=True`. Cost from the config price table; unknown model raises
  `UnknownModelPriceError`.
- `prompts/__init__.py`: `load_prompt(name)` reads `prompts/{name}.md`, error
  lists available prompts.
- `config.py`: added `enable_llm_cache`, `llm_max_tokens`, `llm_retry_attempts`.

**Test results:**
- `make check` → ruff check: all checks passed; ruff format --check: 23 files
  already formatted; pytest (unit): 20 passed, 1 deselected.
- `make test-int` → 1 passed. Real `claude-sonnet-5` call returned
  `answer=42`, 624 input / 33 output tokens, $0.002367, ~1.15s.

**Deferred:** Nothing.

**Non-obvious decisions:** see DECISIONS.md (M1 entries).
