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

## Phase 1: UI shell (2026-10-05)

**Sample data lives in the frontend** (`apps/web/lib/mock.ts`), behind the same types the backend will return, and every page using it shows a **SAMPLE DATA** badge. Sample hooks and scores are illustrative. The sample Circuit City dossier uses only facts and URLs fetched live in Phase 0, and labels everything else *(sample)*, so nothing invented looks like research. Each later phase swaps a page from `useDemo(...)` to a real `useSWR(...)` call.

**`?state=loading|empty|error`** forces any sample-data page into that state, so all three are reviewable without breaking the backend.

**Settings is real.** New endpoints:
- `GET /api/keys`: status of every `.env` value (set / missing / failing), masked previews only. "Failing" comes from the last connection test or the router's auth cooldown.
- `POST /api/system/reload`: re-reads `.env` and config without a restart.
- `GET /api/agents`, `PUT /api/agents/{name}/auto-approve`: stored in the `settings` table, default off.
- `GET/PUT /api/config/{providers|sources|channels|scoring}`: edited as raw YAML so comments survive. Edits are validated with the same Pydantic models the engine uses (provider routes must point at defined models), written atomically, and the router reloads on save.

**Agent registry** (`apps/api/agents/registry.py`) lists v1 agents plus v2 `factcheck` and `graphics` as `available: false`. Adding an agent means one module plus one registry entry.

**Live updates use FastAPI's built-in SSE** (`fastapi.sse.EventSourceResponse`, with automatic keep-alive pings). An in-process `EventBus` keeps the last 50 events so reconnecting clients catch up via `Last-Event-ID`. Phase 1 publishes system events (config saved, provider tested, keys reloaded, settings changed); Phase 2 adds run logs on the same stream.

**`--timeout-graceful-shutdown 3`** on uvicorn. Without it, an open SSE connection (any browser tab) blocks Ctrl+C on `make dev` indefinitely.

**Frontend stack:** shadcn/ui (radix-nova preset, Lucide icons), SWR for API calls, react-markdown + remark-gfm for dossiers. Dark-only theme; the one accent is `--brand` (violet) in `globals.css`. Next 16 notes: route types need `next typegen` before `tsc`, so `pnpm typecheck` runs both. React 19's lint rule forbids `setState` inside effects, so local edits are layered over loaded data rather than copied into state.

**PWA:** manifest plus 192/512/maskable icons, no service worker. Next 16's PWA guide confirms installation doesn't need offline support, and leaving out a service worker avoids serving stale cached pages in dev. Chrome's `Page.getInstallabilityErrors` returns none.

## Re-routing: Mistral and OpenRouter (2026-10-05)

**Why:** the owner can't sign up for Groq, and the Gemini `AQ.`-key rejection is account-wide. Mistral (free "Experiment" tier) and OpenRouter (free models) are added as OpenAI-compatible providers.

**Verified against docs and live endpoints (2026-10-05):**
- **Mistral:** `https://api.mistral.ai/v1`. The free tier is set per workspace: 1 request/s, 500K tokens/min, 1B tokens/month (`admin.mistral.ai/plateforme/limits`). `mistral-small-latest` and `mistral-medium-latest` both have 256K context; `mistral-embed` is 1024-dim. The embeddings request omits `encoding_format`.
- **OpenRouter:** `https://openrouter.ai/api/v1`. Free models allow 20 req/min and 50 req/day (1,000/day after $10 of credits), shared across all free models. The model `google/gemma-4-31b-it:free` was picked from the live `/models` list (it supports JSON mode) and is a different model family from the NVIDIA fallback. The connection test uses `GET /key`, because `/models` is public and wouldn't validate a key.

**Routing:** Mistral leads scoring, parsing, extraction and outliers. NVIDIA is next, and OpenRouter is last for scoring and parsing. `extract_from_document` uses `mistral-medium-latest` with chunks of at most 200K tokens (256K context minus room for the answer). `second_opinion` is NVIDIA then Mistral. `embed` is NVIDIA then `mistral-embed` (different vector spaces, kept separate by model). Groq and Gemini stay at the front of the routes where they were primary before, and are skipped while unavailable: Groq has no key, and Gemini returns 401 and goes into the auth cooldown. `request_budget` now ignores auth-blocked providers, so Gemma's 6K cap doesn't shrink Mistral's batches once Gemini has been rejected. A config test requires every route to include NVIDIA or Mistral.

**Mistral's 1 request/second** isn't paced up front. Calls are sequential and take longer than a second, and a burst 429 is retried with backoff.

**Gemini OAuth: implemented, not verified.** Google's [OAuth quickstart](https://ai.google.dev/gemini-api/docs/oauth) uses `gcloud auth application-default login --client-id-file=client_secret.json --scopes=cloud-platform,generative-language.retriever`. However, google-genai 2.28 only accepts API keys for the Gemini Developer API; OAuth credentials are only used in its Vertex AI mode, and `genai.Client()` with no key raises. So `GeminiOAuthProvider` calls the REST API (`generateContent`, `batchEmbedContents`, `models`) with an ADC bearer token plus `x-goog-user-project`, and is enabled with `GEMINI_AUTH=oauth`. It can't be tested here: `gcloud` isn't installed, and setup needs the owner's Google account (consent screen, Desktop OAuth client, browser login). Steps are in the README. Open question: whether a project whose API keys come out as `AQ.` also gets free-tier access via OAuth. The connection test will show it.

## Gemini OAuth check, Groq primary (2026-10-05)

**Why `GEMINI_AUTH=oauth` didn't take effect:** `.env` had no `GEMINI_AUTH` line (and it wasn't set in the shell), so the engine stayed in API-key mode and reported the `AQ.` key error. The code already gave OAuth priority when the flag is set. Now every connection result includes `auth` (`api_key` or `oauth (ADC)`), shown in `make check-providers` and Settings. With `GEMINI_AUTH=oauth` and no credentials, the message says exactly that instead of "GEMINI_API_KEY is not set". Unknown `GEMINI_AUTH` values log a warning and fall back to the API key.

**OAuth result: not working on this machine, so Gemini stays skipped.** `gcloud` is installed, but `gcloud auth list` shows no credentialed accounts and `gcloud auth application-default print-access-token` fails ("default credentials were not found"), so there's no token for the engine or for curl. The owner's curl results came through as unfilled placeholders, so no successful (HTTP 200) call is on record. Per the owner's instruction, no more time goes into it: Gemini stays in the routes and is skipped. To retry: finish the README steps (the `application-default login` with the Desktop client JSON), confirm `print-access-token` works, set `GEMINI_AUTH=oauth`, and click **Reload .env** then **Test connection**.

**Groq is primary for `score_items` and `parse_mention`** (it was already first in those routes and now has a working key). Verified live: both tasks were served by `openai/gpt-oss-20b` (846 and 485 tokens in, under 1 s each) with no fallbacks.

## Phase 2: jobs, runs, dashboard (2026-10-05)

**Runs only start from approved plans** (hard rule 3). There's no "start a run" endpoint. `POST /api/plans` creates a pending plan, and `POST /api/plans/{id}/approve` (optionally with per-step param edits) enqueues step 1. If every step's agent has auto-approve on, the plan is approved on creation. Steps run one at a time: each starts when the previous one succeeds. A failed or cancelled step marks the plan failed or cancelled and skips the rest. Phase 5's plan cards and orchestrator reuse this service.

**Job runner** (`apps/api/jobs.py`): runs live in `agent_runs`. A loop in the FastAPI lifespan claims queued runs in FIFO order, up to `max_concurrent_runs` (config/engine.yaml, default 2), and runs each agent's `async run(ctx)` as an asyncio task. It's woken on enqueue and otherwise polls. Cancelling a running run cancels its task; cancelling a queued one just marks it. On startup, runs still marked `running` are marked failed ("interrupted"), because a run can't resume mid-way. Agent exceptions fail the run and never crash the runner.

**Logs and progress:** `ctx.log()` writes `run_logs` and publishes `run.log` over SSE. `ctx.step(name, progress)` updates `agent_runs.current_step/progress` (migration 0003) and publishes `run.status`. Router retries, fallbacks and failures are written into the current run's log through a ContextVar (`apps/api/runctx.py`), so provider problems show up in the run itself without the router importing the job system.

**Agent registry** gained `runner` ("module:function"), a params model per agent (`agents/params.py`, the SPEC §6 parameter types), `arrives_in`, and `hidden`. Plans reject agents that aren't built yet, with a message naming the phase.

**`@demo` test agent** (hidden from @-autocomplete): simulated steps, with optional `fail_at`. Home's **Test run** button proposes a demo plan, so the pipeline can be tried end to end without spending any provider quota.

**Quota meters** (`GET /api/usage`) come from `provider_usage` and `agent_runs`:
- "Today" starts at midnight in `engine.yaml` `usage.day_reset_timezone` (America/Los_Angeles, where Google resets).
- Each provider card shows the model and limit closest to its cap, whether daily or per minute, plus calls, errors and fallbacks. Fallbacks come from a new `provider_usage.fallback` flag, set when a call succeeds on a non-primary provider.
- YouTube calls now log their units, with search calls counted separately against the 100/day cap.
- Claude counts today's runs of Claude-using agents against the soft cap.

**Timestamps** use a `UTCDateTime` column type. SQLite drops timezones, so values used to come back naive, and browsers read them as local time.

**Frontend:** Home, run detail and the live panel use real data. SWR refetches (throttled) on `run.*` and `plan.*` SSE events, and the run page appends `run.log` lines without refetching. Cancel is available on the run page and on each active run on Home. Chat, Stories, Research and Outliers still use sample data until their phases.

## Gemini via OAuth works; routes restored (2026-10-05)

**What worked:** the owner completed the OAuth setup, now written up step by step in the README. The steps: Desktop OAuth client JSON in `~/.config/wyrd/`, themselves as a Testing-mode test user, Service Usage Consumer role, Cloud Resource Manager API enabled for `set-quota-project`, `GEMINI_AUTH=oauth` with `GEMINI_API_KEY` commented out. `make check-providers` shows all six providers connected, with Gemini `connected via OAuth` / `oauth (ADC)`. The README has a troubleshooting table for the errors hit on the way (`access_denied`, missing `serviceusage.services.use`, "default credentials not found", `auth: api_key` when the `GEMINI_AUTH` line is missing).

**How the engine uses ADC:** `google.auth.default()` (google-auth library). It never shells out to `gcloud`, so gcloud doesn't need to be on the app's PATH. Tokens refresh on expiry using the ADC refresh token. The quota project comes from the ADC file's `quota_project_id` (overridable with `GOOGLE_CLOUD_QUOTA_PROJECT`) and is sent as `x-goog-user-project`; verified on the live request.

**Expired or missing login:** a refresh failure (e.g. `invalid_grant`, which Testing-mode apps hit about weekly) first re-reads the ADC file, in case the owner just re-logged in. If it still fails, the error tells the owner to rerun `gcloud auth application-default login` and mentions the weekly expiry. If the ADC file is missing, the provider re-checks every 30 s, so a new login is picked up without a restart. These messages appear:
- in Settings: the Gemini row becomes `GEMINI_AUTH=oauth`, showing ADC status, the quota project, and a note;
- once per run in the run log, when Gemini is skipped for missing or rejected credentials;
- via the router's existing auth cooldown.

**Models checked against the live list** (`make check-models`, 61 Gemini models): every configured ID exists. Both `gemini-embedding-2` and `gemini-embedding-2-preview` are listed; the stable `gemini-embedding-2` is kept, and 2048-dim output works.

**Routes:** Gemini Flash-Lite is primary for `extract_from_document` and `analyze_outliers`, with Mistral as first fallback, then NVIDIA (and Groq last for outliers). Flash is primary for deep extraction. Gemini is the first fallback for `embed` (after NVIDIA). Groq stays primary for `score_items` and `parse_mention`, with Gemma second. Verified live: Gemini served `extract_from_document` and `analyze_outliers` (`provider_usage` rows), and its calls show on the Gemini quota meter against the free-tier limits in `providers.yaml`.

## Notion connector (note for Phase 7)

The owner has authorized the Notion connector in their Claude account. In Phase 7 it can be used, interactively from this Claude session, to **create and configure the stories database** (properties: Title, Status, Series, Format, Hook, Scores, Gap Score, Sources, Updated). The **app's own sync** (`notion_sync.py`, the "Sync now" button, auto-sync) still talks to the Notion API with `NOTION_TOKEN` and `NOTION_DATABASE_ID` from `.env`. The app doesn't depend on Claude's connector, so it works without Claude.

## Phase 3: @scout (2026-10-05)

**News pipeline:**
1. Fetch every configured feed and query concurrently. Per-host pacing still applies: GDELT 1 per 5 s, Reddit 1 per 2 s, SEC ≤10/s. With a `topic`, Google News uses `<topic> <suffix>` queries (`sources.yaml` `topic_query_suffixes`), the other sources search the topic itself, and press feeds are filtered to items that mention it.
2. Drop items older than `max_age_days` (30).
3. Exact dedup on normalized URLs (tracking params, `www.`, fragments and trailing slashes stripped) and on headlines with the " - Publisher" suffix removed, against this run and against saved stories' sources and titles. Primary sources (SEC, DOJ, EDGAR) sort first, so they win over re-posts. A matching headline from another outlet is kept as an **extra source** rather than thrown away.
4. Cap at `max_items_to_score` (80), taken round-robin across feeds so no single feed dominates.
5. Semantic dedup with embeddings (cosine ≥ `scoring.yaml` `dedup.embedding_cosine_threshold`), against the other new items and against saved story vectors **of the same model**. If embedding fails, or providers switch models mid-run, semantic dedup is skipped and logged, and exact dedup still applies.
6. Score in chunks of 20, so one failed provider call loses at most 20 items. The run fails only if *every* scoring call fails.
7. Save the top `limit` by weighted rubric score (`scoring.yaml` weights; stored as `scores.total`) with status `Inbox`, their sources (primary/secondary plus a short excerpt), and an embedding for future dedup.

**Gap finder:**
1. Crawl categories (`per_category`). Batch-fetch article lengths (50 per request), and fetch references, summary and pageviews only for the `max_articles_detailed` longest articles, to keep Wikipedia calls bounded.
2. Pre-score those articles, then run a YouTube coverage check for the top `top_n_for_youtube_check`: one `search.list` ("<name> company story", 10 results) plus one `videos.list` for view counts. Each check costs 2 units and **1 search call**.
3. **Budget:** checks = min(top N, search calls left today minus `search_calls_reserve`, units left minus `units_reserve` ÷ 2). Both limits come from `provider_usage` since today's Pacific-midnight reset; each YouTube call already logs itself there. Checking stops early on a quota/403 error. Popular coverage = videos ≥ `youtube_view_threshold` views whose titles contain the company name.
4. Gap score (0–10) = weighted quality + richness + low coverage (`scoring.yaml`). Richness = 50% references, 25% length, 25% log-pageviews, each normalized to a configurable "full" value. Only coverage-checked articles get a gap score and are saved; the run notes say when the budget limited checks.

**`both` mode** splits `limit` between news (rounded up) and evergreen.

**Plan cards show an estimate:** agents can register `estimate(params)`. Scout's is the upper bound of YouTube search calls and units (0 for news), shown on the plan card next to the daily caps.

**`series`** adds `prompts/scout_series_hint.md` to the scoring prompt (prompt text stays in prompts/), and stories in that series rank first. Scores also return an optional `company`.

**Stories page is real:**
- New endpoints: `GET /api/stories` (filters plus FTS5 search), `GET /api/stories/{id}` (sources, dossier versions), and `PATCH /api/stories/{id}` (status/series/format/notes/hook; publishes `story.changed`).
- The board's drag-and-drop updates status optimistically, then confirms with the server.
- **Run @scout** (Stories page and ⌘K) opens a parameter form, then the plan card; nothing runs before approval.
- The scout run summary is stored in the run result. Posting it to chat comes with the orchestrator in Phase 5.

**Live verification (2026-10-05):**
- **News run** (`mode=news, limit=10`): fetched 245 items from 15 feeds and queries, dropped 10 exact and 5 semantic duplicates (NVIDIA embeddings), scored 75, and saved 10 stories with sources, hooks and series. Reddit returned 429 for two subreddits (logged and skipped), so `www.reddit.com` pacing went from 2 s to 7 s.
- **Gap finder** (`mode=evergreen`): 171 articles from 5 categories, 60 read and pre-scored, and **20 YouTube coverage checks = 20 search calls / 40 units** (today's usage went from 0 to 20 searches, within 100 − 10 reserve). It saved the 4 highest gap scores, e.g. the British Post Office scandal at 9.21 with no popular videos. Blockbuster (6 popular videos) and Circuit City (3) ranked lower.

**Fixes from the live runs:**
- The plan-card estimate capped YouTube checks at `limit`, but the run checks the top N (20). The estimate now matches the run, and a test enforces it.
- Google News "snippets" that just repeat the headline are no longer stored as excerpts.
- Board drag-and-drop carries the story id in `dataTransfer` instead of relying on React state.

**Mistral has zero quota on this account.** Its chat responses carry `x-ratelimit-limit-req-minute: 0`, so every call is a 429. The key itself is valid, which is why the old models-list connection test passed. Now:
- a 429 with a limit of 0 is treated as a **block** (`ProviderError.block`): Mistral is skipped for the auth cooldown with a message naming the limits page, instead of being retried;
- Mistral's connection test is a 1-token chat call, so it reports this honestly.

The owner needs to activate the free Experiment plan (or check limits) at `admin.mistral.ai/plateforme/limits`.

**Scoring speed is the bottleneck: 8 minutes for 75 items.** Groq's free tier allows 8K tokens per minute, so after the first batch it's near its limit and the router uses fallbacks. Gemini returned 500/503 ("high demand") during the runs, and Mistral is blocked (above), so NVIDIA (~30 s per batch) did most of the work. Every item was still scored. Ways to speed it up: a working Mistral quota, a paid Groq tier, or lowering `max_items_to_score`.

**Scout hooks are leads, not research.** They're generated from the headline and snippet with "don't invent facts" in the prompt, but they're unverified. Verified facts only come from @researcher dossiers (Phase 6).
