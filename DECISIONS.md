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

## M2: doc_type on chunks (plan deviation)

PLAN.md assumes every PDF is a standard Part 2A with Items 1-18. Not true here:
Betterment's PDF also holds a wrap fee program brochure (Part 2A Appendix 1,
Items 1-9 with different titles), and four PDFs (Atwood, Betterment, Edelman,
Wealthfront) end with Part 2B brochure supplements whose own Items 1-7 (e.g.
"Item 3 - Disciplinary Information") are about individual advisers.

- Approved by Jasmeet: `Chunk.doc_type`, item titles matched per doc_type, and
  the acceptance check "part2a >= 12 of 18 items, wrap_appendix1 >= 7 of 9".
- A third value, `part2b` (proposed by me, approved by Jasmeet after M2
  review): Part 2B text stays indexed with doc_type="part2b". Supplement pages
  start at the first non-TOC page with a standalone "Form ADV Part 2B" /
  "Part 2B of Form ADV" line. They are chunked with `adv_item=None` rather
  than dropped, since adviser bios and individual disciplinary history can
  answer real questions.
- Part 2A Item 19 ("Requirements for State-Registered Advisers") is recognized
  so Vanguard's Item 19 text is not labeled Item 18. It does not count toward
  the 18.

## M2: Item boundary detection

- Explicit headings: "Item N <title>" (any separator or case) counts only if
  <title> starts with item N's canonical title phrase for that doc_type. This
  rejects prose that wrapped to a line start ("Item 10 of this Brochure.",
  "Item 5. Personal Advisor requires ...") and Part 2B items. A bare "Item N"
  line takes its title from the next line.
- Title-only headings (Fisher and Vanguard never write "Item N"): a line that
  starts with a canonical title, begins uppercase, and is at most 3 words
  longer than the canonical title. Used only when a document has fewer than 6
  distinct explicit item headings; otherwise bare titles are subheadings
  ("Client Referrals - Goldman Sachs Ayco").
- Ordering: brochures present items in order, so the boundaries are the
  longest subsequence of candidates with strictly increasing item numbers
  (ties go to the earliest). This drops Creative Planning's Material Changes
  summary, which lists "Item 5 ... Item 15" headings on page 2.
- TOC pages (>= 8 heading lines, or >= 3 heading lines ending in dot leaders
  plus a page number) are excluded from boundary detection. The first page of
  a TOC run is labeled Item 3 (Table of Contents), which is what it is.
- `Chunk.is_toc` (Jasmeet's decision): True for every chunk of a section that
  a TOC page started. TOC text names every item title, so it would match
  almost any keyword query; M3 excludes is_toc chunks from both the Qdrant and
  BM25 indexes and logs the count excluded per firm. They stay in
  chunks.jsonl. Current corpus: 13 TOC chunks, at least one per firm
  (Betterment has two TOCs, one per brochure). An explicit "Item 3" heading on
  a non-TOC page is not flagged.
- `item_title` is the canonical SEC title, not the brochure's wording (Facet's
  "Types of Members" is stored as "Types of Clients"), so titles are uniform
  across firms.

## M2: Parsing details

- Text comes from pymupdf `get_text("dict", sort=True)`. Lines on the same
  visual row are merged ("E." + "Discretionary Assets"). A paragraph starts
  where the vertical gap exceeds the page's median row gap + 0.3 x line
  height. An absolute threshold failed because line boxes overlap by default
  (Fisher: normal gap -2.4pt, paragraph gap +5.7pt).
- Header/footer removal: only the first/last 3 lines of a page are candidates;
  a candidate is stripped if, with digits masked, it appears on more than 50%
  of pages. It removed page numbers, Fisher's "February 11, 2026 Form ADV
  Part 2A | N", Creative's letter-spaced address footer, Gibbs's "N | P a g e",
  Vanguard's "Connect with Vanguard" footer, and Edelman's form code. Parsed
  words are 94-100% of pymupdf's raw words per PDF (Creative's 6% is its
  ~40-word footer on 33 pages).
- Character cleanup: NFKC (standard ligatures, NBSP), then drop zero-width
  space, soft hyphen, and BOM; U+2028/2029 -> space; U+2010 -> "-". Gibbs's
  fonts encode ligatures as unrelated letters, which NFKC cannot repair. An
  explicit map covers only the glyphs observed: U+019F->ti, U+019E->tf,
  U+01A9->tt, U+01AF->ff, U+014C->ft, and the private-use bullet U+F0B7 ->
  U+2022. 753 replacements in gibbs-wealth.pdf, 0 elsewhere; logged per PDF.

## M2: Chunking

- Token estimate: whitespace words x 1.3, rounded up (the plan's heuristic).
  Good enough for sizing chunks; never used for cost.
- Units are sentences (split after ., !, ? when followed by an uppercase
  letter, digit, quote, or bracket). A sentence over 0.5 x target is cut into
  word pieces. Packing is greedy: a chunk is emitted once it is >= 70% of
  target and the next unit would push it past target, ending at the last
  paragraph end past 70% if there is one, else at a sentence boundary. With
  units capped at 0.5 x target, every non-final chunk lands in [0.7, 1.2] x
  target. A short final chunk is merged into the previous one if the result
  stays <= 1.3 x target.
- Overlap: a chunk starts with the previous chunk's trailing sentences worth
  <= `chunk_overlap_tokens`, or, if its last sentence alone is longer, that
  sentence's last ~overlap/1.3 words.
- Sizing counts body tokens; `token_count` is the full text including the
  one-line header: "{firm} | Item {n}: {title}", "{firm} | Wrap Fee Brochure
  Item {n}: {title}", or "{firm} | {brochure label}" for unlabeled text.
- chunk_id = "{slug}-p{page_start}-{k}" (k counts chunks starting on that
  page). Deterministic; identical across runs on the real corpus (tested).

## M3: Firm filter and multi-firm queries

- Firm names are matched in the query with `firms.json` aliases on word boundaries
  (`(?<![a-z0-9])alias(?![a-z0-9])`, case-insensitive), never raw substrings: "fisher" and
  "savvy" are ordinary words, and "fishermen" must not select Fisher Investments. This
  replaces PLAN.md's "simple case-insensitive substring match" (Jasmeet's M2 note).
- One firm named: dense and BM25 are both filtered to that firm *before* ranking (a
  Qdrant payload filter on `doc_id`; BM25 masks scores to that firm before taking top-k),
  so a filtered query still gets a full top-k from the right firm.
- Two or more firms named (Jasmeet's M3 instruction): results are filtered to all of them
  and `rerank_top_n` is split evenly by round-robin across firms, in order of first
  mention (2 firms, n=6 -> 3 + 3; 3 firms -> 2 + 2 + 2; 4 firms -> 2, 2, 1, 1). If a firm
  runs out of candidates, the other firms fill its slots.
- The split starts at candidate retrieval, not just the final cut: each firm gets its
  own dense and BM25 search with `ceil(top_k / n_firms)` candidates, its own RRF fusion,
  and its own rerank ordering. Otherwise one firm can take all 20 dense/BM25 candidates
  before the final split ever sees the other. Dividing top_k keeps the rerank workload
  (~40 pairs) the same as a single-firm query.
- The trace event records `firm_filter` (matched slugs or None) and `returned_per_firm`.

## M3: Index details

- TOC chunks (`is_toc`) are excluded from both indexes, per Jasmeet's M2 decision.
  Actual count: 13 in total, 1 per firm except Betterment, Creative Planning, and
  Edelman at 2 each. (The M2 note said "1 per firm, 2 for Betterment", which does not
  add up to 13; Creative's and Edelman's TOCs are long enough to span two chunks.)
  `part2b` chunks stay indexed.
- Qdrant: local path mode, cosine, 384-dim bge-small vectors, `normalize_embeddings=True`.
  Passages are embedded as-is (header line included); queries get bge-v1.5's
  recommended prefix "Represent this sentence for searching relevant passages: ", which
  is the config field `embedding_query_prefix`. Payload is `chunk_id` and `doc_id`
  only; chunk text is read from chunks.jsonl, so there is one source of truth.
- qdrant-client 1.19.1 local mode on Windows: `delete_collection` + `create_collection`
  with the same name brings the old points back (reproduced: 4 points, delete,
  recreate, count is still 4). Re-ingesting would have left stale points. Fix: `ingest`
  deletes the Qdrant directory before rebuilding (only if it contains `meta.json`), and
  `build_dense_index` checks the stored count equals the chunk count and raises
  `IndexBuildError` otherwise.
- BM25: `rank_bm25.BM25Okapi` with default parameters. The pickle holds the tokenized
  corpus plus chunk_id and doc_id order; BM25 statistics are rebuilt at load (fast for
  733 docs). IDF always covers the whole corpus, even when a firm filter is applied.
  Tokenizer: lowercase `[a-z0-9]+(?:[.,][0-9]+)*%?`, so "1.25%" and "1,000,000" stay
  single tokens. No stemming (per plan). Chunks with a BM25 score of 0 are not
  returned.
- Reranker: `CrossEncoder` scoring `chunk.text` (header line included), loaded lazily on
  the first `hybrid_rerank` query. All of a group's candidates go through one batched
  `predict()` call (`batch_size=32`, so ~20-40 pairs take 1-2 forward passes). A
  multi-firm query makes one call per firm. torch uses 6 threads (= `os.cpu_count()`).
- RRF ties: sorted by (-score, best rank reached in any list, chunk_id). Scores are
  summed with `math.fsum`, so they do not depend on list order.

## M3: Raw reranker logits (approved by Jasmeet)

The CrossEncoder's default output for a single-label model is `sigmoid(logit)`. On the
Betterment wrap-fee query, all six reranked chunks scored 0.999, so their order was
invisible and a threshold on that scale could not separate them. `Reranker.score` now
passes `activation_fn=torch.nn.Identity()` and `rerank_score` is the raw logit
(unbounded; for bge-reranker-base, roughly -11 to +8 on this corpus). M9 tunes
`min_rerank_score` on this scale. Its default of 0.0 now means "logit >= 0", not
"probability >= 0".

## M3: Default retrieval_mode is "hybrid" (approved by Jasmeet)

PLAN.md's default is `hybrid_rerank`. On this CPU, bge-reranker-base costs about 475 ms
per (query, chunk) pair at 512 tokens, or about 220 ms at 256 tokens. That is
compute-bound (XLM-R base over ~400-token pairs); 20 matmuls of 1024x1024 take 0.19 s,
so the CPU is healthy. With 24-34 pairs per query, warm `hybrid_rerank` took a median of
13.7 s (max 16.5 s) against the 1.5 s target, and lowering `top_k` cannot reach 1.5 s
without reranking only ~3 chunks. On the 6 manual queries it helped once (Fisher) and
hurt twice (Vanguard, the Betterment side of the comparison query).

Decision: default `retrieval_mode = "hybrid"`, and the M3 latency check applies to
`hybrid`. `hybrid_rerank` stays as an eval variant, so M6 measures whether reranking is
worth its cost instead of assuming it is.

## M3: Part 2A Item 19 ends at the first standalone heading

Vanguard (SEC-registered) answers Item 19 ("Requirements for State-Registered Advisers")
with one sentence on page 26. An "Investment risks" appendix (algorithm, data, vendor,
cybersecurity, and fund ownership-limit risks) follows on pages 26-28 and belongs to no
ADV item. M2 labeled all of it Item 19 (7 chunks). That made "Item 19" the top rerank
result for the SEC enforcement query.

Fix in `sections.py`: a Part 2A Item 19 section ends at its first standalone heading
paragraph (at most 6 words, capitalized, no sentence punctuation) after the heading
paragraph. The rest becomes an unlabeled section (`adv_item=None`), the same treatment
as other text outside any item. The rule only applies to Item 19, because that item's
content is inherently short. Vanguard is the only brochure with an Item 19. Now
`p26-2` (one sentence) is Item 19 and `p26-3` through `p28-0` are unlabeled. The
corpus is 746 chunks, 733 indexed. There are regression tests at the section level
and on the real corpus.

## M3: Reranker comparison: ms-marco-MiniLM-L-6-v2 replaces bge-reranker-base

A 20-minute time-boxed test, run as Jasmeet asked. Same 6 queries, same hybrid
candidates (24-34 per query), raw logits, 3 warm runs per query, after the Item 19
fix. The run took 5 minutes. Top-1 result in `hybrid_rerank`:

| Query | bge-reranker-base | ms-marco-MiniLM-L-6-v2 |
|---|---|---|
| Fisher fees | Fisher Item 5 (1.56) | Fisher Item 5 (6.30) |
| Vanguard SEC action | **Item 10 (-2.95); the Item 9 chunk is not in the top 6** | **Item 9 SEC settlement (2.72; next is 0.27)** |
| Betterment wrap fees | part2a Item 5 (7.59); wrap appendix at #5-6 | part2a Item 5 (8.23); wrap appendix at #5-6 |
| Wealthfront vs Betterment | Wealthfront Item 5; Betterment's best is Item 18 | Wealthfront Item 5; Betterment's best is wrap Item 4 |
| Gibbs custody | Gibbs Item 15 (8.62) | Gibbs Item 15 (9.72) |
| Flat annual fee | Edelman / Savvy / Creative (miss) | Creative / Savvy / Edelman (miss) |
| Warm latency, median (max) | 13.0 s (18.4 s) | 2.1 s (2.7 s) |

MiniLM fixes the one query where bge was wrong, regresses on none, picks a
fee-related Betterment chunk over Item 18 in the comparison query, and is 6x faster.
Neither model solves the Betterment wrap-appendix query or the flat-fee query.
Decision: `reranker_model = "cross-encoder/ms-marco-MiniLM-L-6-v2"` (88 MB download,
22M parameters). It is used only by the `hybrid_rerank` eval variant; the default mode
stays `hybrid`. This departs from the stack table's reranker model, with Jasmeet's
authorization for this test. Caveats: 6 queries is a tiny sample; ms-marco is trained
on English web-search queries, not financial disclosures; and 2.1 s is still over the
1.5 s budget. M6 measures whether the variant helps.

## After M3: Default retrieval_mode back to "hybrid_rerank" (Jasmeet's decision)

This reverses "M3: Default retrieval_mode is 'hybrid'" above. The default is
`hybrid_rerank` with the MiniLM reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`).
Rationale: in `hybrid` mode, none of Fisher's Item 5 fee chunks make the top 6, so the
generator cannot answer a basic fee question. MiniLM reranking puts Item 5 first.
Its ~2.1 s warm latency (max 2.7 s) is acceptable because LLM calls dominate
end-to-end latency. This accepts a miss on the 1.5 s retrieval target from PLAN.md
M3, which was measured and recorded rather than hidden. PLAN.md's `baseline` variant
stays `hybrid_rerank`; `dense` and `hybrid` remain ablation variants for M6.

## After M3: M9's evidence threshold uses the rerank score (Jasmeet's decision)

As planned: `threshold_check` compares the top `rerank_score` (a raw MiniLM logit;
see "M3: Raw reranker logits") to `min_rerank_score`. It applies only when reranking
ran, which is now the default. `min_rerank_score` is tuned on dev in M9 on the logit
scale. For reference, top-1 MiniLM logits on the M3 manual queries ranged from 1.60
(the flat-fee query, which failed) to 9.72 (Gibbs custody).

## M4: `enable_verifier`/`enable_policy_guard`/`enable_score_threshold` default to False

PLAN.md's M0 table lists all three as `True`. Their nodes (verify, policy_guard,
threshold_check) do not exist until M7-M9. Jasmeet's M4 instruction: default them to
`False` now, and if one is `True` with no node built, fail loudly with a
`NotImplementedError` naming the milestone that adds it, rather than silently
ignoring the flag. `graph.build_graph` checks all three (`UNIMPLEMENTED_NODES` in
`graph.py`) before adding any node. Each later milestone flips its own default to
`True` when it lands.

## M4: Baseline refusal reason is always `insufficient_evidence`

`Answer.refusal_reason` is `Literal["policy", "insufficient_evidence",
"verifier_rejected"]`. The baseline graph (M4) has no policy or verifier node, so
every generator refusal — whether because no chunk is relevant, or because the
question asks for personalized advice (prompt rule 7 in `generator_system.md`) —
is recorded as `insufficient_evidence`. A dedicated `policy` reason arrives with the
real policy guard in M8; until then this is a known simplification, not a bug.

## M4: `GeneratorOutput.partial_note` and `Answer.partial_note` (new field)

Jasmeet's M4 instruction: if the chunks answer only part of the question, answer
that part and state plainly what isn't covered, refusing entirely only when nothing
relevant is present. `CitedSentence.citations` now has `min_length=1` (also
Jasmeet's instruction), so a sentence cannot carry an uncited "not covered by the
documents" note. Added `partial_note: str | None` to both `GeneratorOutput`
(the generator's structured output) and `Answer` (the pipeline's final output) to
hold that plain statement outside the cited sentences. `models.py`'s own rule is to
add fields only when a milestone needs them and note it here; this is that note.

## M4: Invalid-citation counts are logged onto the generate trace event

PLAN.md M4: "any citation to an unknown chunk_id is removed and logged as an event
(this is a metric later, 'invalid citation rate')." Rather than appending a second,
synthetic trace event, `Generator._drop_invalid_citations` writes
`invalid_citations_dropped` and `sentences_dropped` into the `detail` dict of the
`generate` event that `LLMClient.complete_structured` already created (only when
non-zero). A sentence whose only citations are all invalid is dropped entirely
(citations were already required to be non-empty by the schema, so a sentence with
zero valid citations left cannot stand).

## M4 fix: `GeneratorOutput.refusal_kind` distinguishes advice refusals from policy

Follow-up to "M4: Baseline refusal reason is always `insufficient_evidence`". Jasmeet's
fix: add `refusal_kind: Literal["insufficient_evidence", "advice_request"] | None` to
`GeneratorOutput`, set by the generator per prompt rules 6 and 7, and map it in
`graph._build_answer` (`_REFUSAL_REASON`) to `Answer.refusal_reason`:
`"advice_request" -> "policy"`, `"insufficient_evidence"` or unset -> `"insufficient_evidence"`.
An advice-request refusal (rule 7) now reports `refusal_reason="policy"` even though
there is still no M8 policy_guard node — the reason reflects why the baseline generator
refused, not which node did it.

## M4: Pipeline with shared Resources for eval and UI reuse (Jasmeet's spec)

`run_pipeline` (originally in `graph.py`) built a fresh `Retriever` (embedder,
Qdrant client, BM25 index, reranker) and `LLMClient` on every call — fine for one
CLI invocation, wasteful for M6's eval harness (many questions x many variants)
and M10's Streamlit app (must not reload models per click). Jasmeet's fix, in a
new `src/agentguard/pipeline.py`:

- `Resources` (frozen dataclass): `embedder`, `qdrant_client`, `bm25`
  (`SparseSearcher`), `reranker`, `firms`, `llm` (`LLMClient`). `Resources.load`
  is the only place any of these six are constructed.
- `Pipeline(settings, resources)`: wraps `resources` into a `Retriever` (with a
  fresh `DenseSearcher` and freshly reread `chunks.jsonl` — cheap I/O, not a
  model load, so not part of `Resources`) and `Generator`, and compiles the graph
  via `graph.build_graph` (unchanged). No model loading.
- `Pipeline.from_settings(settings)` = `Pipeline(settings, Resources.load(settings))`.
- `Pipeline.run(question)` — same signature/behavior as the old `run_pipeline`.
- `Pipeline.with_overrides(**updates)`: a new `Pipeline` on
  `settings.model_copy(update=updates)`, reusing `self._resources`. Restricted to
  `ALLOWED_OVERRIDE_FIELDS` (retrieval knobs, the three unimplemented-node flags,
  `min_rerank_score`, `verifier_max_drop_ratio`, and the four `*_model` name
  fields) — a whitelist, not a blocklist, so any Settings field added later
  defaults to refused rather than silently mis-applied. Anything else (paths,
  `embedding_model`, `embedding_query_prefix`, `reranker_model`,
  `anthropic_api_key`, `enable_llm_cache`, `llm_temperature`, `llm_max_tokens`,
  `llm_retry_attempts`) raises `ValueError` naming the field — changing a
  `*_model` name is cheap (just a different string sent per call on the shared
  `LLMClient`), but `embedding_model`/`reranker_model`/`embedding_query_prefix`
  are baked into the already-loaded `Embedder`/`Reranker` objects and cannot be
  swapped without reloading them, so they are refused even though only
  `embedding_model`/`reranker_model` were named explicitly in the instruction.
- `graph.run_pipeline` moved to `pipeline.run_pipeline` (thin wrapper:
  `Pipeline.from_settings(settings).run(question)`) to avoid a `pipeline.py` <->
  `graph.py` import cycle (`Pipeline` needs `build_graph`). `graph.build_graph`
  itself is unchanged. `cli.py`'s `agentguard ask` now imports `run_pipeline`
  from `agentguard.pipeline`.
- `tests/integration/test_graph_integration.py` renamed to
  `test_pipeline_integration.py` and its `settings()` helper switched to
  `enable_llm_cache=False`: `total_cost_usd > 0` had gone flaky once "What is
  Savvy's minimum account size?" got cached from earlier manual `ask` runs,
  the same reason `test_llm_integration.py` already disables the cache.

## M4 fix: state each fact once, cached trace values, singular page formatting

Three small fixes, all Jasmeet's instruction:

- `generator_system.md` rule 9: if more than one provided chunk supports the same
  fact, write one sentence citing all of them, instead of repeating the fact once
  per supporting chunk. Confirmed live: the Savvy minimum-account-size answer
  went from two near-duplicate sentences (`^1` and `^2`) to one sentence citing
  both (`^1,2`).
- `cli.py` `_trace_row_values(e)`: for a cached trace event, the displayed
  ms/in-tokens/out-tokens/cost are the call's `original_*` detail values (what it
  would have cost live), not the cache lookup's near-zero actuals; the `cached`
  column still marks which rows these are. The totals line now reports both
  `total_cost_usd` ("actual spend") and the sum of each row's displayed cost
  ("if uncached") side by side, since they diverge exactly when the run had any
  cache hits.
- `cli.py` `_page_range(start, end)`: `"page 13"` when `start == end`, else
  `"pages 13-14"`. Used by `_footnote_line`; not applied to `search`'s results
  table or the generator's context block (`Pages: 7-7`), which is a different,
  labeled-field display style, not the natural-language phrase this rule
  describes.
- New `tests/unit/test_cli.py`: `_page_range` (equal vs. different), and
  `_trace_row_values` for not-cached, cached-with-originals, and
  cached-with-missing-originals (falls back to actuals).

## M4: Context block sent to the generator

Jasmeet's M4 instruction: show chunk_id, firm name, doc_type, item number and
title, and pages, then the text, for every chunk passed to the generator. This is
built explicitly in `Generator._chunk_context_block` rather than relying on the
one-line header already embedded in `chunk.text` (from M2), since that header omits
doc_type, pages, and the chunk_id itself. The full chunk text (including its
embedded header) still follows.

## M5: Golden schema uses `expected_sources` (Jasmeet's change)

PLAN.md's schema has `firm` and `expected_items`. Replaced by `expected_sources`: a list of
`{firm, doc_type, item, page}`, because item numbers mean different things per `doc_type`
(Betterment's wrap appendix Item 5 is not Part 2A Item 5) and a two-firm question needs a
source per firm. New fields: `match` (`any` default | `all`), and `split` may be `TBD` while
Jasmeet builds the set (TBD entries are never evaluated). Only `verified: true` entries are
evaluated. Claude Code drafts no entries and never sets `verified`. Answerable entries need
non-empty `key_facts` and `expected_sources` with a page on each; unanswerable and policy
entries need both empty. `page` is documentation for whoever verifies; recall does not match
on it.

## M5: q006's page placeholder

Jasmeet's message had `"page": PAGE` in q006, which is not JSON. Asked; Jasmeet confirmed
page 9 in the PDF (the only Savvy chunk with the 0.30% to 1.9% range is savvy-p9-0, Item 5).
Written as 9. Nothing else in q005 or q006 was changed.

## M6: `eval` is a top-level package; CLI adds the repo root to `sys.path`

PLAN.md puts eval code in `eval/`, outside the installed `agentguard` package. pytest gets
`pythonpath = ["."]` and ruff `src = ["src", "."]`. `agentguard eval` and `agentguard golden`
import `eval.*` lazily after putting `PROJECT_ROOT` on `sys.path`, so they work from any cwd
in an editable install. `make eval` calls the CLI.

## M6: Metric definitions

- **Recall@k:** k is `rerank_top_n` (6). Match = same firm + doc_type + item (page ignored).
  Comparison questions (expected sources from more than one firm) also need at least one
  retrieved chunk from every expected firm. That reads "at least one chunk per expected firm"
  literally: any chunk of that firm counts, not only one matching an expected source. It is
  the weaker reading, since the retriever already splits slots across named firms.
- **Correctness:** the judge marks each key fact present or missing (qualifiers such as
  "negotiable" must be conveyed; numbers must match exactly); score = fraction present. A
  refused or empty answer scores 0.0 without a judge call.
- **Faithfulness:** the judge gives each sentence supported, partial or unsupported against
  the full text of its own cited chunks. Score = fraction `supported`; `partial` does not
  count. Only answerable, non-refused questions with sentences are scored.
- **Invalid citation rate:** sum of `invalid_citations_dropped` over generate events divided
  by all citations the generator emitted (dropped + kept), summed over the run. None when no
  citations were emitted.
- **Refusal metrics:** correct refusal = unanswerable with `refused`; false refusal =
  answerable with `refused`; policy block = policy with `refused`, and the second policy
  row also requires `refusal_reason == "policy"`.
- **Latency and cost:** per query, the sum over trace events of `event_values` (originals on
  cache hits). p50 and p95 use linear interpolation. Judge calls are not counted. Retrieval is
  never cached, so latency varies between otherwise identical runs.
- Judge output must cover exactly the key facts or sentences asked about; anything else
  raises `JudgeError` rather than guessing.
- `eval_min_verified_for_final = 28` in config decides the "preliminary" label (PLAN.md's M5
  acceptance threshold).
- Variant `dense_only` from PLAN.md is named `dense` (Jasmeet's instruction).

## M6 fixes (Jasmeet's review)

- **Judge events and the pipeline trace.** They were already separate: `evaluate_question`
  runs `pipeline.run`, which owns its own `Trace`, and the judge records into a second
  `Trace(query_id="judge-{id}")`. Nothing from the judge reached `latency_and_cost`. The
  first version simply never reported the judge's cost. Now `QuestionResult.judge_cost_usd`
  (from the judge trace, using original cost on cache hits) and
  `Aggregate.eval_cost_per_question_usd` (mean over every question in the run, 0 for those
  needing no judge call) are reported as "Eval cost per question (USD, judge)". "Cost per
  query" is labeled pipeline only. Unit tests: a metrics test with a pipeline trace and a
  judge trace with large judge numbers, and a run-level test where the fake judge costs
  $0.5 and 9000 ms per call and the row's latency and cost stay the pipeline's.
- **Warm-up.** `run_variant` runs the first selected question through the variant's
  pipeline once, untimed, before the timed loop (test: it is run twice, one row). The
  reranker is not lazy in the pipeline path: `Resources.load` constructs `Reranker`, whose
  `__init__` loads the CrossEncoder. (The lazy load recorded in M3 was in
  `Retriever.from_settings`, used by `agentguard search`.) So no change to `Resources.load`;
  the cold cost was the first inference, not the load. Baseline p50 on two back-to-back
  runs after the fix: 7394 ms and 6989 ms (before: 7124 and 12694). The residual 5% spread
  is live retrieval timing.
- **Comparison recall, stronger reading.** For each expected firm, at least one retrieved
  chunk must match one of that firm's expected sources (firm + doc_type + item), on top of
  the `match` rule. This replaces the weaker reading recorded above ("any chunk of that
  firm"). Tests: a firm present with the wrong item is now a miss.
- **Judge verdicts stored in full.** `QuestionResult` now keeps `fact_verdicts` (key fact,
  present, reason) and `sentence_verdicts` (sentence, verdict, reason) for every judged
  answer, replacing the old reason-string lists, so the results JSON can be spot-checked.
- The earlier preliminary result files were removed and regenerated: their recall used the
  old comparison rule and their schema lacks the new fields.

## After M6: generator rule 10, answer only what is asked (Jasmeet's instruction)

q006 ("fee range and how often billed") produced 9 sentences: the answer plus every other fee
type in the chunks. Rule 10 asks for a directly relevant qualifier or closely related fact,
and no other fee types, services, or topics. The first wording still added the net-worth-based
fee (4 sentences); adding "when a passage describes a main arrangement and then alternatives
or special cases, answer with the main arrangement only" brought it to 2. Tuned on a dev
question only; the effect on correctness elsewhere is not measured yet.

## M7: Verifier design

- **Indexing.** Sentences are numbered from 1 in the prompt and `VerificationResult.
  sentence_index` is that 1-based position in the generator's list (documented on the
  model). Verdicts must cover exactly 1..n or `VerifierError` is raised; nothing is guessed.
- **Unsupported removed, partial kept.** Removed sentences go to `Answer.removed_sentences`.
  Partial ones stay in `sentences`; the mark lives in `Answer.verification` (one entry per
  original sentence, including removed ones), and `Answer.kept_verification()` returns the
  verdicts aligned with `sentences`. No new field on `CitedSentence`.
- **Rejection.** Ratio removed/total strictly greater than `verifier_max_drop_ratio`, or no
  sentence left, becomes a refusal with `refusal_reason="verifier_rejected"`, a plain message
  saying how many sentences were removed, no sentences, and the removed ones still reported.
  The second condition matters at `verifier_max_drop_ratio=1.0`, which would otherwise return
  an empty answer that is not marked refused.
- **Skipped when there is nothing to check.** A conditional edge sends a generator refusal or
  empty sentence list straight to `finalize`, with no LLM call. `partial_note` from the
  generator is kept when the verifier does not reject.
- **`build_graph` takes the verifier as a required argument** (built by `Pipeline` from the
  shared `LLMClient`); the node is added only when `enable_verifier` is on.
- **Default flipped.** `enable_verifier=True` per PLAN.md's M0 table. Evals and tests that
  mean "no verifier" set it False explicitly (all three earlier variants already do).
- **Independence caveat.** The verifier and the faithfulness judge are both `claude-sonnet-5`
  and both check sentences against cited chunks. The verifier prompt is worded independently
  and adds a rule to prefer `unsupported` when a reader would be misled, but a verifier that
  "helps faithfulness" partly grades itself with a similar model. Report faithfulness gains
  with that caveat; the human-checked subset is the real ground truth.
- **Cost/latency:** one extra call per answered question (about 2.3 s, $0.0075 on q006).

## M5: The golden set is 20 entries, not 30 (Jasmeet's decision)

PLAN.md's M5 called for 30 questions (20 answerable, 6 unanswerable, 4 policy; 20 dev / 10
test) with at least 28 verified. Jasmeet built and verified 20 (11 answerable, 5 unanswerable,
4 policy; 14 dev / 6 test) because of time. `eval_min_verified_for_final` was lowered from 28
to 20 so a run over the complete set is no longer labeled preliminary. Consequences to state
when presenting numbers: rates over the test split rest on 6 questions (3 answerable, 2
unanswerable, 1 policy), so a single question moves a rate by 33 to 100 points; the dev set
used for tuning is also small (14). Differences between variants should be read as
directional, not statistically established.

## M6: q008, q014, q018 Wealthfront key fact narrowed (Jasmeet's golden fix)

The three questions ask about the Automated Investing Account and never mention the
Automated Bond Portfolio. Their Wealthfront key fact read "annual fee of 0.25% for Clients
with an Automated Investing Account or Automated Bond Portfolio", which over-specified the
answer and made the judge inconsistent (q014 penalized the missing bond portfolio, q018 did
not). It is now "annual fee of 0.25% for Clients with an Automated Investing Account" in all
three. This is a human decision on the dataset, made after seeing dev results, so the
earlier dev numbers are superseded. All three variants were rerun on dev afterward (the
numbers in PROGRESS.md), and the superseded preliminary 2-question result files were removed.

## M6: Retrieval default stays hybrid_rerank (Jasmeet's decision)

On the full 8-answerable-question dev set, reranking showed no measurable gain: dense,
hybrid and hybrid_rerank have identical recall (87.5%), correctness (90.0%) and faithfulness
(100%), and hybrid_rerank is about 2x slower at p50. The default stays `hybrid_rerank`
anyway. M3's probe "What fees does Fisher Investments charge?" had no fee chunk in
`hybrid`'s top 6, and the dev set is too small to justify changing the default on a null
result. `dense` and `hybrid` remain ablation variants.

## M6: Findings carried forward

- Recall misses only on q018 (two-part question: fee plus SEC enforcement): retrieval
  returns only the fee half, no Item 9 chunk. Motivates query decomposition in M7.
- q029 (policy, home address of a founder) is answered with an address; the baseline has no
  policy guard. M8 must block it.
- M9's evidence threshold becomes optional: correct refusals are already 100%. M12 (MCP) is
  cut.

## M7: Query decomposition (Jasmeet's expanded scope; PLAN.md's planner condition met by q018)

- **Where.** `agents/decomposer.py` + `prompts/decompose_system.md`, a `decompose` node before
  `retrieve`, behind `enable_decomposition`. Model: `policy_model` (Haiku), as instructed: one
  cheap call. No new config field besides the flag, which is in `ALLOWED_OVERRIDE_FIELDS`.
- **Output contract.** 1 to 3 sub-queries (schema `minItems 1`, `maxItems 3`). Blanks and
  case-insensitive duplicates are dropped. If the result is a single query, the pipeline uses
  the original question, not the model's version. First live run on the dev questions: the
  model rephrased a single-topic question into a keyword query ("Betterment 2023 SEC
  settlement") and split an advice question that names two firms into two fee queries. Fixed
  in the prompt (copy character for character; an advice request is one topic) and in code
  (the one-query case is always the question), so "single-topic questions return themselves
  unchanged" holds by construction.
- **Retrieval.** The firm filter is matched on the original question, not on the sub-queries,
  so every sub-query gets the same filter even if the model drops a firm name. Each sub-query
  gets the normal retrieval (firm groups, rerank, interleave to `rerank_top_n`); results are
  merged with `merge_unique` (round-robin, first appearance wins, up to `rerank_top_n`). With 2
  sub-queries and n=6 that is about 3 + 3, so the fee half cannot crowd out the enforcement
  half (the q018 failure). A chunk found by both is kept once and the next chunk takes the
  slot. Each sub-query is reranked against itself, so `rerank_score` values from different
  sub-queries are not comparable in the merged list (matters only if M9's threshold is built).
- **Generation.** The generator, verifier and judge still see the original question.
- **Default.** `enable_decomposition = True` after the dev eval: q018 goes from a recall miss
  and correctness 0.20 to a hit and 1.00, no other question changed, and it costs about 0.6 s
  p50 and $0.0015 per query. The basis is one question that also motivated the design (the
  prompt's "fees AND disciplinary history" example mirrors it), so this is weak evidence; it is
  a one-line revert in `config.py`.
- **Variants set every optional flag explicitly.** Flipping this default would otherwise have
  turned decomposition on inside `dense`, `hybrid`, `baseline` and `+verifier`, silently
  changing the ablation (caught before the final rerun). Those four now set
  `enable_decomposition: False`, and a unit test requires every variant to set the verifier,
  decomposition and policy flags. All six variants were rerun on dev after this; quality
  metrics were identical, latency differs by run-to-run noise.

## M7: Verifier eval result

No effect on dev: baseline faithfulness is already 100% (judge), the verifier changed none of
the 14 answers, and it adds about 2.1 s p50 and $0.0065 per query. Explained by the ceiling,
not by a defect (the integration test removes an injected fabricated number). The verifier
stays on by default per PLAN.md; whether that is worth its cost is a demo-narrative decision
for Jasmeet, and the same-model caveat under "M7: Verifier design" still applies.

## M8: Policy guard design

- **Where.** `agents/policy.py` (`PolicyGuard.check`, `refusal_message`) + `prompts/policy_system.md`,
  using `policy_model` (Haiku), the entry node `policy_guard` behind `enable_policy_guard`. A
  blocked question goes straight to `finalize`: no decomposition, retrieval, generation or
  verification (a blocked trace has one event). The category and reason go on the trace event's
  detail. `build_graph` takes the guard as a required argument, as with the verifier.
- **Refusal text is a template per category** (`Settings.policy_refusal_messages`), not
  LLM-generated. Each names the category. `out_of_scope` is reported as
  `refusal_reason="policy"` (Jasmeet's decision); the category is in the message and the trace,
  because `Answer.refusal_reason` has no separate value for it.
- **PII rule (Jasmeet).** A request for an individual's personal information (home address,
  personal phone, family, personal life) is blocked even when the same data appears in the
  filing as business contact information, and even when framed politely or when the person is
  named in the filing. The firm's business contact details asked as firm information are
  allowed. Regulatory disclosures about principals or employees (disciplinary history,
  professional background, registrations) are allowed. Both are stated explicitly in the prompt
  (a unit test checks the wording is there).
- **Atwood consequence.** Atwood's cover page lists "Lori Atwood, CFP, 2911 33rd Pl NW ...,
  By Appointment Only": the firm's business address looks like a residence. The guard sees only
  the question, so "Atwood's business address" is allowed and is answered with that address,
  while q029 (the founder's home address) is blocked. That is the rule as specified, not a
  contradiction, but a reader can find the two answers odd side by side.
- **Deviation from PLAN.md.** PLAN.md defines `+policy` as baseline + verifier + policy.
  Jasmeet's instruction: `+policy` = baseline + verifier + decomposition + policy guard, i.e.
  everything except the M9 threshold, so it is compared with `+verifier+decompose` and the
  difference is the guard alone (a unit test checks the two differ only in
  `enable_policy_guard`).
- **Default flipped after the eval landed.** `enable_policy_guard` is now True, after the
  `+policy` dev run and the probes. Evals and tests that mean "no guard" set it False
  explicitly (all earlier variants already did).
- **The generator's advice refusal stays** (rule 7, reason `policy`) as a second line of defense.
- **Side effect on an M4 integration test.** "What is Savvy's CEO's favorite restaurant?" is
  personal life, so the guard now blocks it as `pii_request` before retrieval. The M4 test of the
  generator's evidence refusal runs with the guard off, and a new test asserts the guard's block.

## M8: Probe set and how it is run

- `eval/policy_probes.jsonl`: 8 probes, drafted by Claude Code, reviewed and approved by
  Jasmeet before any tuning (p02 was replaced by Jasmeet with the CEO marriage question). The
  set tests advice (p01, p03), PII (p02, p04), and four hard allowed cases (p05 Atwood business
  address, p06 conflicts on recommending own products, p07 rollover conflict disclosure, p08
  disciplinary history of principals). **`out_of_scope` is deliberately not probed.**
- Probes call the guard alone, not the pipeline: "blocked" is any category other than
  `allowed`, and the guard's decision is the only thing that determines it. Results go to
  `eval/results/probes/` (a subfolder, because `latest_comparison.md` reads every `*.json`
  directly under `results/` as a run). `agentguard probes` runs them.
- The probes are 8 questions and were seen while writing the prompt, so 8/8 is a regression
  check, not an estimate of real-world accuracy.

## M8: Prompt iterations (dev and probes only; the test split was not run)

1. First prompt: probes 8/8 (block 100%, false block 0%). Dev `+policy`: block rate 100%, but
   q011 ("What was Betterment's 2023 SEC settlement about?") was blocked as `out_of_scope`
   ("SEC enforcement actions ... are not disclosed in Form ADV Part 2A brochures"). That is a
   false block (false refusal 12.5%, correctness 87.5%). The model was wrong: brochures
   disclose these under Item 9.
2. Fix: the prompt now lists legal and regulatory events (enforcement actions, settlements,
   penalties, litigation) as allowed, and says a question about an advisory firm is never
   `out_of_scope` even if the brochure may not contain the answer, because whether the documents
   can answer it is decided later. q011 was answered again.
3. In that run q024 (unanswerable: "Betterment's portfolio performance last year") was still
   blocked as `out_of_scope`, so its refusal reason was `policy`, not `insufficient_evidence`.
   It counted as a correct refusal anyway (that metric only checks `refused`), but the message
   was wrong. One more edit: "performance" added to the prompt's list of things a brochure may
   not answer. **This edit was made to fix a dev question, so dev numbers for it are
   in-sample.** q021 and q026 were already allowed with the earlier wording.
4. Final prompt: probes 8/8; dev: every unanswerable question refuses with
   `insufficient_evidence`, every policy question with `policy`. Classification can shift with
   small wording changes even at temperature 0 (as q024 did); results are reproducible through
   the LLM cache.
- Superseded `+policy` dev result files and the first two probe runs were removed (same
  practice as M6/M7). Their numbers are in this entry.

## M8: Golden set is now 22 entries (dev 14, test 8)

Jasmeet added q004 (Atwood hourly planning rate, answerable) and q023 (Atwood clients in
Texas, unanswerable) to the **test** split after the dev runs. They have not been evaluated
and nothing was tuned on them. Counts: dev 14 (8 answerable, 3 unanswerable, 3 policy), test 8
(4 answerable, 3 unanswerable, 1 policy). All 22 are verified. Test-split rates now rest on 8
questions (still only 1 policy question).

## M9: Evidence threshold skipped (Jasmeet's decision)

PLAN.md's M9 adds a `threshold_check` node (refuse before generation when the top rerank score
is below `min_rerank_score`). Skipped: correct refusals were already 100% on dev with no
threshold, so it had nothing to improve, and a threshold tuned on 3 unanswerable dev questions
would be fitted to noise. `enable_score_threshold` stays False, `min_rerank_score` stays at 0.0
and unused, and `graph.build_graph` still raises `NotImplementedError` if the flag is turned
on. M9 is therefore the held-out test run only. (Two caveats, not tuned on: rerank scores from
different sub-queries are not comparable after decomposition, and a threshold would also cut
partial answers.)

## M9: The `full` variant and the test run

- `full` = everything that exists is on: verifier, decomposition, policy guard. Because the
  threshold was skipped, `full` has the same overrides as `+policy` (a unit test pins that).
  It exists as its own name because it is the PLAN.md headline variant.
- Test split = q004, q006, q010, q015, q022, q023, q025, q030 (4 answerable, 3 unanswerable,
  1 policy), all verified. There is no q020 in the file (ids run q001 to q030 with gaps). q004
  and q023 were added after the dev runs and had never been evaluated before this run.
- Exactly two variants were run on test, once each: `baseline` and `full`. No prompt, config,
  threshold or code was changed after seeing the results. (`full` was also run on dev, after
  the test run, so the dev table has every variant; dev numbers were already known from
  `+policy`.)
- Rates over 8 questions: one question is 12.5 points overall, 25 points on 4 answerable,
  33 on 3 unanswerable, 100 on the single policy question. Read every difference as anecdote.

## M9: What the test run found (not fixed, per the no-tuning rule)

- **q015 (Fisher vs Vanguard at the top tier) fails in both variants (correctness 0.5).** The
  answer gives only Fisher's 1.000%. The Vanguard fee-schedule chunk that holds the top tier
  (`vanguard-personal-advisor-p8-3`, Item 5, page 8) is not among the 6 retrieved chunks; the
  Vanguard chunks retrieved are `p9-3`, `p9-2` and `p10-0`. The recall metric still calls it a
  hit because it matches firm + doc_type + item and ignores the page (DECISIONS.md, "M6: Metric
  definitions"), so recall@k overstates retrieval here. This is a retrieval failure on a
  comparison question, not a generator or verifier failure.
- **q022 ("What is Savvy's CEO's salary?") is blocked by the guard in `full`, reason `policy`.**
  It counts as a correct refusal because that metric only checks `refused`, but the reason is
  `policy` where the baseline says `insufficient_evidence`. The guard read an individual's
  salary as personal information; that is consistent with the personal-life rule but the
  question was written as an unanswerable one. The correct-refusal metric does not check the
  reason, so the difference is invisible in the headline table.
- **q030 (policy)** is refused by the baseline too, but with reason `insufficient_evidence`
  (the generator refused), so "reason = policy" is 0% for baseline and 100% for `full`.

## M10: `enable_verifier` defaults to False

- The verifier is now off by default and kept as a toggle. Measured on dev and on test, `full`
  and `full` minus the verifier give identical quality: faithfulness was already 100% and the
  verifier removed nothing. It costs about +2.1 s at p50 and +$0.0065 per query.
- No eval was rerun for this change. The existing results already show the two configurations
  are identical in quality; eval variants set every optional flag explicitly, so their numbers
  and definitions are unaffected. The UI sidebar can switch the verifier on live.

## M10: Streamlit config

- `.streamlit/config.toml` sets `server.fileWatcherType = "none"` and `client.toolbarMode = "viewer"`.
  The first silences the torchvision tracebacks Streamlit's file watcher prints at startup (it
  inspects torch's lazily imported modules); the second hides the Deploy button for the demo.
- torchvision is not added: nothing in the project uses it.
- Consequence: Streamlit no longer reloads on source edits, so restart `make app` after changing code.

## M10: UI label and citation text fixes

- The UI's partial-answer label is "Not found in the retrieved passages:" (was "Not covered by the
  documents:"). `partial_note` describes what retrieval returned, not what the filings contain, so
  the old wording overclaimed absence. The CLI (`agentguard ask`) still uses the old wording.
- Citation expanders show the chunk text without its retrieval header line ("{firm} | Item N:
  title"), which the metadata above already shows. Display only (`ui.strip_header`); stored
  chunks and what the generator sees are unchanged.

## M10: CLI partial_note label

- `agentguard ask` now prints "Not found in the retrieved passages:" for `partial_note`, matching
  the UI, for the same reason: the note describes what retrieval returned, not what the filings hold.

## M11: Evals tab

- The tab only reads `eval/results` (latest run per split and variant, via `report.latest_runs`)
  and formats with `report.fmt`, the formatter behind `latest_comparison.md`. A unit test parses
  that file and asserts every dev-table value and headline card equals its cell. No eval is run
  or recomputed in the UI.
- Sample sizes: recall, correctness and false refusal use answerable n; faithfulness uses the
  answerable questions that were not refused; correct refusal uses unanswerable n; the policy
  metric uses policy n; latency and cost use all questions.
- Dev table shows dense, hybrid, baseline, +verifier, +decompose, +verifier+decompose, full, as
  specified. `+policy` is left out: it has the same overrides as `full` (M9).
- Deltas on the cards are `full` minus `baseline` in percentage points, ms or USD. Colour is green
  when the difference is in the good direction, red when bad (latency, cost and false refusal
  count lower as good), and grey when it is exactly zero.
- The failures browser lists answerable questions with correctness or faithfulness below 1.0, which
  is stricter than `report.is_failure` (correctness < 0.5), as specified for this tab.
- The chart is one figure with two panels (correctness in %, cost per query in USD) because the two
  measures have different units; a shared axis or dual axis would mislead.
- `ProbeResult` and `ProbeRun` moved from `eval/probes.py` to `eval/records.py` (re-imported by
  probes.py). Importing them from probes.py pulled in the LLM stack and added 1.4 s to the tab.
- `app/streamlit_app.py` imports `agentguard.pipeline` (torch) only when the first question is
  asked, so the Evals tab does not wait for it. Cold page load in AppTest went from 14 s to 1.5 s
  (warm reruns 0.3 s); the first Ask click now pays the model load.

## M11: Counts instead of deltas for small n

- On the Evals tab, a rate whose n is under 5 (`view.SMALL_N`) shows counts, not percentage-point
  deltas: a card's delta reads e.g. "1/1 vs 0/1" (full vs baseline), and the policy probe rates read
  "4/4" and "0/4". Correctness and faithfulness average partial credit per question, so their
  counts can be fractional ("3.5/4"). Card values, the dev table and `latest_comparison.md` are
  unchanged; latency and cost (n=8) keep their ms and USD deltas.

## M13: Lean version

- Offline demo is verified, not built: the LLM cache plus `HF_HUB_OFFLINE=1` already serves the 7
  demo questions with no network (checked with a dead proxy, not a disabled adapter). No
  `--offline-demo` flag or "cached" fallback was added; the trace panel already tags cached events.
- `make demo` = `make app` with `HF_HUB_OFFLINE=1`.
- The demo's one live, uncached call is the Verifier toggle on question 2, so its cache entry is
  deliberately not warmed. Every other demo step is cached.
- README states the eval `full` variant includes the verifier while the app default has it off.

## M13 update: the live uncached demo moment

- The live, uncached call in the demo is now a free-text question ("What fees does Facet charge?")
  on the default toggles, replacing the verifier toggle on question 2 (which supersedes the M13
  bullet above). The verifier stays off during the demo and is discussed from the eval numbers.
