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

## M1: Model price table source (corrected)

Fetched https://docs.claude.com/en/docs/about-claude/pricing on 2026-09-23; it
302-redirects to https://platform.claude.com/docs/en/about-claude/pricing.
Relevant rows from the Model pricing table (base input / output):

    | Claude Sonnet 5  | $2 / MTok(3) | ... | $10 / MTok(3) |
    | Claude Haiku 4.5 | $1 / MTok    | ... | $5 / MTok     |

Footnote 3: "The $2/$10 per million input/output token pricing for Claude
Sonnet 5, announced at launch as introductory pricing through August 31, 2026,
is now the standard price. The previously scheduled increase to $3/$15 per
million input/output tokens on September 1, 2026 will not occur."

Correction: the M0 table had Sonnet 5 at $3/$15, and the first M1 commit
recorded it here as "checked" when it had not been re-fetched. It is now
$2/$10. Prompt-caching discounts are ignored (we don't use Anthropic prompt
caching). A model missing from the table raises rather than costing $0.

## M1: One LLM call = one trace event

`complete_structured` opens its own `trace_node(trace, node_name)`, so each LLM
call appears as one event carrying model, tokens, cost, `cached`, and
`attempts`. Tokens and cost from the corrective retry are summed into the same
event. Non-LLM nodes (retrieval etc.) use `trace_node` directly.

## M1: Retry and cache details

- The Anthropic SDK retries internally by default; set `max_retries=0` so
  tenacity is the only retry layer and the policy is visible in one place.
- Added config fields not in the M0 list, all needed to avoid hardcoding:
  `enable_llm_cache` (the toggle M1 asks for), `llm_temperature` (0.0),
  `llm_max_tokens` (required API parameter, 2048), `llm_retry_attempts` (5).
- A cache entry is `{"result": ..., "usage": {input_tokens, output_tokens,
  cost_usd, duration_ms}}`. On a hit the event keeps `cost_usd=0` (nothing was
  spent) but `detail` carries `original_*` values, so eval reports can show what
  a query really costs instead of a fake $0 / ~5ms. `original_duration_ms` is
  the wall time of the API call(s) including any corrective retry.
- The result is stored as `model_dump(mode="json")` and re-validated on read,
  so a cached result is an equal (not the same) object of the requested type.
- The cache key includes a `CACHE_FORMAT_VERSION` (now 2), so entries in the
  old layout are ignored rather than misread.
- A response with no tool call (e.g. `stop_reason=max_tokens`) is treated as a
  validation failure and gets the same single corrective retry.

## M1: Prompt loader location

`load_prompt` lives in `src/agentguard/prompts/__init__.py` so the directory
that holds the `.md` prompts also owns loading them.

## M1: Paths anchored to PROJECT_ROOT

`PROJECT_ROOT = Path(__file__).resolve().parents[2]` (valid for the editable /
src-layout install we use). All path defaults and `env_file` are absolute under
it; a relative path given via env/`.env` is resolved against PROJECT_ROOT, not
the cwd. This makes the CLI, Streamlit, and the MCP server (which Claude
Desktop launches from an arbitrary cwd) all see the same files.

## M1: Temperature is sent only to models that accept it

Planned: pass `llm_temperature=0.0` on every call. Not possible as written:
- anthropic SDK 1.8.0's `messages.create` has no `temperature` argument.
- The API reference marks it deprecated: "Models released after Claude Opus 4.6
  do not support setting temperature."
- A test call on 2026-09-23 with `extra_body={"temperature": 0.0}`:
  `claude-sonnet-5` → 400 "`temperature` is deprecated for this model";
  `claude-haiku-4-5-20251001` → accepted.

Decision (approved by Jasmeet): `MODELS_WITHOUT_TEMPERATURE` in config lists
models that reject it (`claude-sonnet-5`). For every other model,
`llm_temperature` is sent via `extra_body`. The temperature actually sent
(or `None`) goes into the cache key and into `event.detail["temperature"]`.
Consequence: generator, verifier, and judge (all Sonnet 5) run at the model's
default sampling and cannot be pinned. Eval reproducibility comes from the
diskcache, not from temperature. A fresh uncached rerun may differ slightly;
report that if it happens.

## M2 prep: Brochure files, firms.json, and Betterment's two-part PDF

The 10 brochures were downloaded under their SEC numeric IDs and renamed to
Jasmeet-approved slugs (`data/raw/{slug}.pdf`). They are committed to the repo
(5.9 MB total, public SEC filings) so a fresh clone runs end to end.

`data/raw/firms.json` extends the PLAN's `{"slug": "Display Name"}` format to
`{"slug": {"name", "aliases", "doc_type"}}`. Aliases are lowercase (short name,
legal name, d/b/a) for M3's firm filter. Short abbreviations ("vai", "fea",
"efe") are deliberately left out because they collide with ordinary tokens.

`betterment.pdf` is two brochures in one file: a standard Part 2A (Items 1-18,
pages 1-34) followed by its Wrap Fee Program Brochure (Form ADV Part 2A
Appendix 1, Items 1-9, pages 35-83). Item numbers mean different things in
each half (Item 5 is "Fees and Compensation" vs. "Account Requirements and
Types of Clients"), so doc_type must be per chunk, not per firm. Decision
(approved by Jasmeet): Betterment's firms.json entry carries
`"wrap_appendix1_from_page": 35`; pages from 35 on are parsed as
`wrap_appendix1`. The PDF is not split, so citations keep the real SEC page
numbers and one slug stays one firm.
