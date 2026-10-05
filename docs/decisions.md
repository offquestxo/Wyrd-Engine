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
