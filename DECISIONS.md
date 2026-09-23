# Decisions

Short log of non-obvious technical decisions and why they were made.

## M0: GNU make installation

`make` was not present on the dev machine. `choco install make` failed (needs
admin rights this shell doesn't have). Installed `ezwinports.make` via
`winget install --scope user` instead, then copied the resulting `make.exe`
into `~/.local/bin` (already on PATH) since winget's own PATH update doesn't
propagate to already-running shells. No project files depend on this; it's a
one-time machine setup note for whoever else clones the repo on Windows
without `make`.

## M1: Model price table source

`MODEL_PRICES_PER_MILLION_TOKENS` in `config.py` comes from
https://docs.claude.com/en/docs/about-claude/pricing (checked 2026-09-23):
`claude-sonnet-5` $3 in / $15 out, `claude-haiku-4-5-20251001` $1 in / $5 out,
per million tokens. Prompt-caching discounts are ignored (we don't use Anthropic
prompt caching). A model missing from the table raises rather than costing $0.

## M1: One LLM call = one trace event

`complete_structured` opens its own `trace_node(trace, node_name)`, so each LLM
call appears as one event carrying model, tokens, cost, `cached`, and
`attempts`. Tokens and cost from the corrective retry are summed into the same
event. Non-LLM nodes (retrieval etc.) use `trace_node` directly.

## M1: Retry and cache details

- The Anthropic SDK retries internally by default; set `max_retries=0` so
  tenacity is the only retry layer and the policy is visible in one place.
- Added three config fields not in the M0 list, all needed to avoid hardcoding:
  `enable_llm_cache` (the toggle M1 asks for), `llm_max_tokens` (required API
  parameter, 2048), `llm_retry_attempts` (5).
- The cache stores `model_dump(mode="json")` and re-validates on read, so a
  cached result is an equal (not the same) object of the requested type.
- A response with no tool call (e.g. `stop_reason=max_tokens`) is treated as a
  validation failure and gets the same single corrective retry.

## M1: Prompt loader location

`load_prompt` lives in `src/agentguard/prompts/__init__.py` so the directory
that holds the `.md` prompts also owns loading them.
