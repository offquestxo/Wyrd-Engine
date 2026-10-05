# Decisions

Choices not covered by SPEC.md, newest last. Each keeps v1 simple and v2 easy.

## Phase 0 — 2026-10-05

**Repo at root, not `story-engine/`.** Owner's call. The GitHub repo is the project root.

**Python 3.12 pinned via `uv`** (`.python-version`). Meets the 3.11+ requirement; the system Python (3.9) is untouched.

**Plain-SQL migrations instead of Alembic.** `apps/api/db/migrations/NNNN_*.sql` run once each, in order, tracked in `schema_migrations`. The SQL files are the schema source of truth. The SQLModel classes mirror them, and `tests/test_db.py` fails if the two drift. FTS5 uses external-content tables kept in sync by triggers.

**`provider_usage.error` column added** (not in SPEC §7). It stores a short error message for failed calls so the dashboard can show why a provider failed.

**Prompts beyond SPEC's list:** `prompts/parse_mention.md` (the @mention fast path needs a prompt) and `prompts/json_repair.md` (the router's one repair retry). Prompts get `{{output_schema}}` filled from the Pydantic model, so the schema and the validator never disagree. Fetched content is passed in the user message inside `<data>` tags, and every prompt says to treat it as data.

**Groq and NVIDIA via plain `httpx`, Gemini via `google-genai`.** Both are OpenAI-compatible, so one small client (`openai_compat.py`) covers them without the OpenAI SDK.

**Per-model extra request fields in config** (`extra:` in `providers.yaml`). Examples are NVIDIA's `input_type` for embeddings and `enable_thinking: false` for Nemotron. Provider quirks stay out of code.

**Router fallback/retry events** are kept in an in-memory ring buffer (`Router.events`) and logged. Failed attempts are also rows in `provider_usage` (`ok=0`). Phase 2 can persist them if the dashboard needs history across restarts.

**Near-limit handling:** a model at ≥90% (`near_limit_ratio`) of any known per-minute or per-day limit, counted from `provider_usage`, is tried after the other providers rather than skipped outright.

**`extract_from_document` drops quotes not found verbatim in the document.** This enforces research integrity in code as well as in the prompt.

**Source HTTP politeness:** one shared helper (`sources/_http.py`) paces requests per host (intervals in `sources.yaml`: SEC ≤10/s, GDELT 1 per 5 s, Reddit 1 per 2 s) and retries 429/5xx twice. A contact User-Agent (`SEC_USER_AGENT`) is sent to every source, which SEC and Wikimedia ask for.

**Wayback "closest snapshot" uses the CDX API** (`sort=closest`). The separate `archive.org/wayback/available` endpoint returned 429 during testing.

**YouTube quota model changed upstream.** As of 2026-10, `search.list` costs 1 unit but has a separate cap of **100 calls/day**. SPEC §4 assumed 100 units per call. `providers.yaml` tracks both `units_per_day: 10000` and `search_calls_per_day: 100`; the gap finder (Phase 3) must budget search *calls*, not units.

**NVIDIA model IDs come from the live `/v1/models` list.** The docs pages listed some IDs (e.g. `meta/llama-3.3-70b-instruct`, `nvidia/llama-nemotron-embed-1b-v2`) that the API no longer serves. Chosen: `nvidia/nemotron-3-super-120b-a12b` (chat) and `nvidia/nemotron-3-embed-1b` (embeddings).

**Embedding spaces differ by model.** NVIDIA and Gemini vectors aren't comparable, so `embeddings.model` is stored and similarity is only computed within one model. If the router falls back to Gemini embeddings, those items are compared against other Gemini vectors.

**Phase 0 web app is a placeholder** (create-next-app with Geist and Tailwind) so `make dev` runs both servers. Phase 1 replaces it with the real shell.

**`make test` runs offline tests only.** Network tests are marked `live` and run with `make test-live`.

## Phase 0 follow-up: Gemini limits and routing (2026-10-05)

**Gemini "AQ." keys are a Google-side issue, not a code bug.** The SDK (google-genai 2.28) already sends the key in the `x-goog-api-key` header. Plain `curl` with the same header returns the same 401. Google's forum has many reports of new `AQ.`-format AI Studio keys being rejected while standard `AIza` keys work. The provider now returns an actionable message for this case.

**Owner's AI Studio free-tier limits are now in `providers.yaml`.** Routing:
- `score_items` / `parse_mention`: Groq → Gemma 4 31B (`gemma-4-31b-it`) → fallbacks. Groq is skipped while it has no key, so Gemma leads; setting `GROQ_API_KEY` makes Groq primary with no config change.
- `extract_from_document` and `analyze_outliers`: Gemini 3.5 Flash-Lite primary. NVIDIA is added as the last fallback for `analyze_outliers` so it works without Groq.
- New `extract_from_document_deep` route (Gemini 3.8 Flash, 20 requests/day). `extract_from_document(..., deep=True)` uses it, for @researcher `depth=deep` only.
- `second_opinion` fallback changed from Flash to Flash-Lite, to keep Flash's 20 requests/day for deep extraction.

**Per-model `json_mode` and `max_request_tokens`.** Gemma's Gemini API docs don't list JSON mode, so it is off for Gemma (the router validates and repairs instead). Gemma thinking is set to `MINIMAL`. `score_items` is split into batches estimated under the smallest `max_request_tokens` among usable route models (6K for Gemma and Groq, under their 16K/8K TPM). `extract_from_document` splits documents on paragraph boundaries into chunks under that budget (200K for Flash/Flash-Lite), queries each chunk, and merges the results. Token counts are estimated at about 4 characters per token, with no tokenizer.

**Known limit:** two back-to-back 200K-token chunks exceed Flash-Lite's 250K TPM. The second chunk then goes to the next provider (≥80% rule) or waits through a 429 retry. A rate-aware wait can come later if large filings hit this often.

**`near_limit_ratio` lowered to 0.8** (owner request).

**Gemini client is cached per event loop.** The SDK's async transport is bound to the loop that created it, and reusing it across loops (CLIs, tests) raised "Event loop is closed".

**`make check-models`** compares configured model IDs with each provider's live model list. The Gemini embedding ID is ambiguous in the docs (`gemini-embedding-2` vs `gemini-embedding-2-preview`); this check will settle it once a Gemini key works.

## Gemini unavailable for now (2026-10-05)

**Status:** the owner's Gemini key is `AQ.`-format and is rejected with HTTP 401 (see above). Google Cloud Console may also issue `AQ.` keys, so Gemini is treated as **unavailable until a working key exists**. Nothing is removed: Gemini stays in every route and is used automatically once `.env` has a working key (restart the API to reload `.env`).

**Every route that uses Gemini ends with NVIDIA**, and `tests/test_config.py` enforces it. Verified live with the `AQ.` key: `parse_mention`, `score_items`, `extract_from_document` (standard and deep), `analyze_outliers`, `second_opinion`, and `embed` all returned valid results via NVIDIA.

**Auth-failure cooldown.** After a 401/403, the router skips that provider for `auth_failure_cooldown_s` (900 s) instead of paying for a rejected request on every call. It then tries again; a passing "Test connection" or an API restart clears the block immediately. While Gemini is down, NVIDIA's ~40 RPM is the bottleneck for scoring and extraction.
