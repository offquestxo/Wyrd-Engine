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

## Faster scoring, unverified hooks, v2 roadmap (2026-10-05)

**Parallel scoring** (`providers/parallel.py`): `score_items` batches go to every usable provider in the route at once instead of one after another.
- **Lanes:** each provider/model is a lane with its own worker(s) and batch size (`max_request_tokens`, capped by tpm × `safety_ratio`). Each lane has a 60-second rate window (rpm and tpm from providers.yaml, seeded with the last minute of real usage from `provider_usage`), and a lane at ≥98% of its daily rpd/tpd doesn't start.
- **Failures:** failed batches go back on the queue for any lane. A lane drops out on a block (bad credentials or zero quota) or after `max_failures_per_lane` failures in a row.
- **OpenRouter** (`last_resort`) only takes work after all other lanes have dropped out, which protects its 50 free requests/day.
- **Hedging:** when the queue is empty, an idle lane re-runs any batch that's been in flight longer than `hedge_after_s` (30 s). The first result wins and the slower request is cancelled once every item is scored.
- **Run logs** name the provider/model that scored each batch, and stories store `scores.scored_by`.
- **Result:** 75 live items scored in **47 s** (was ~8 min): Groq 19, NVIDIA 56, with Gemini's 500s hedged around. Mistral is blocked by its zero quota and joins automatically once the Experiment plan is active.
- **Groq fix:** gpt-oss at default reasoning effort failed Groq's JSON validation (`json_validate_failed`); `reasoning_effort: low` (providers.yaml `extra`) fixed it, at about 1 s per batch.

**Pre-filter** (`scoring.yaml` `prefilter`): before any LLM call, news items are dropped if the headline has too few words, matches a noise pattern (advice threads, recipes, sports, promos), or comes from Hacker News/Reddit without a business keyword (whole-word match, so "sec" doesn't match "second"). The run log reports counts per rule.

**Unverified hooks:** scout hooks show an **UNVERIFIED LEAD** badge (with an explanation tooltip) in the Stories table, the board and the detail drawer. Verified facts come only from @researcher dossiers.

**v2 roadmap** added to SPEC.md §13 (Phases 8–10, plus @factcheck and scheduled runs later). Not built. Changes to Phases 4–7 that make it easier:
- **Phase 4 (@outlier):** keep `channels`/`videos` generic, with an `is_own` flag on channels, so Phase 10 can store the owner's videos and analytics in the same tables. Store duration, publish time and thumbnail URL per video.
- **Phase 5 (chat):** the browser should call the API **through the web app's own origin**: Next.js forwards `/api/*` to 127.0.0.1:8000 instead of the browser calling `http://127.0.0.1:8000` directly. Then a single `tailscale serve` of port 3000 works on a phone, where 127.0.0.1 would mean the phone. SSE must stream through that proxy (verify, or serve `/api` on a separate tailnet path). Build the chat UI responsive from the start.
- **Phase 6 (@researcher):** besides the markdown, store Key Numbers, Timeline, quotes and locations as **structured JSON** in `dossiers.sources_json` / a new field, each with source URL and excerpt. @graphics then renders counters, charts, timelines, quote cards and map pins straight from verified data. Define the `[GRAPHIC: type | value | source#n]` cue syntax in the dossier export so Script Room scripts are parseable later.
- **Stories:** add `video_url` / `published_at` (set when status → Published) so Phase 10 can join analytics to stories and their scores. Mirror them in Notion in Phase 7.
- **Google OAuth:** Gemini uses ADC with fixed scopes. Phase 10's YouTube Analytics access should use **its own stored OAuth token** (read-only YouTube scopes, possibly a different Google account) rather than widening the ADC login, so a weekly Gemini re-login never breaks analytics and vice versa.

## Phase 4: @outlier (2026-10-05)

**Shorts rule** (support.google.com/youtube/answer/15424877): a video is a Short if it's square or vertical and ≤ 180 s (≤ 60 s for uploads before 2024-10-15). Aspect ratio comes from `videos.list` `player.embedWidth/embedHeight` (fitted into a 1000×1000 box), at no extra quota cost; verified live (long 1000×563, Shorts 563×1000).

**Medians** are computed per channel and per format, only from videos ≥ `min_age_days` (3) old and only when there are ≥ 5 of them. Newer videos aren't flagged or listed. Outlier score = views ÷ median.

**Units:** per channel, 1 lookup (only if the channel ID isn't cached) + ceil(n/50) uploads + ceil(n/50) stats. `estimate()` uses the same formula, and the run logs estimate vs. actual. Live: 9/9 units (first scan), then 7/7 (two channels cached).

**Seed handle fix:** `@companyman` is a different, tiny channel. Company Man is `@companyman114` (1.8M subscribers). Channel lookups now log subscriber and video counts so a wrong handle is obvious.

**Create story from outlier:** makes an Inbox story with `outlier_ref`, the analysis angle as an (unverified) hook, and a YouTube source. Calling it twice for the same video doesn't create a duplicate.

## Phase 5: orchestrator + chat (2026-10-06)

**Claude Code headless flags** (checked with `claude --help`, v2.1.196). One `claude -p` process per chat turn, with the prompt sent on stdin:

| Flag | Why |
|---|---|
| `-p --output-format stream-json --verbose --include-partial-messages` | Streamed events: `text_delta`s for live text, `assistant` blocks for tool calls, `rate_limit_event`, and a final `result` (duration, `num_turns`, usage, `session_id`) |
| `--session-id <uuid>` on the first turn, `--resume <uuid>` after | One Claude session per chat. We generate the UUID and store it on `chats.claude_session_id` only after a successful turn |
| `--model sonnet --effort low` | From `engine.yaml` `orchestrator`, to keep Pro usage down |
| `--system-prompt <prompts/orchestrator.md>` | Replaces the default system prompt. The agent list and parameters come from the params models, and channel handles from `channels.yaml`, so the prompt can't drift from the code |
| `--mcp-config <json> --strict-mcp-config` | Only the engine's MCP server, over HTTP with `X-Wyrd-Chat` and `X-Wyrd-Token` headers |
| `--tools ""` | No built-in tools: no shell, no file reads or edits, no web |
| `--allowedTools mcp__wyrd__…` | Our 7 tools, pre-approved. The list is generated from the MCP registry |
| `--permission-mode dontAsk` | Anything else is denied, never prompted |
| `--setting-sources "" --disable-slash-commands` | No user hooks, plugins or skills in the orchestrator |

- The working directory is `~/.local/share/wyrd/orchestrator` (configurable), outside the repo, so the project's CLAUDE.md isn't loaded into every chat turn. Claude Code keys saved sessions by working directory, so it must stay fixed.
- **MCP connect race:** sometimes the session starts before the MCP server connects. The init event then shows it as `pending`, with no tools, and Claude writes fake tool calls as text (seen once live). Fix: if init doesn't show `wyrd` as `connected`, the process is killed right away, before any model call, and retried up to 3 times. A first turn retries with a fresh session id. If it still fails, the turn ends with a clear error rather than a made-up reply. An undocumented `MCP_CONNECTION_NONBLOCKING` env var might control this, but it isn't relied on.
- **Rate-limit signal:** Claude Code's `rate_limit_event` (`allowed` / `allowed_warning` / `rejected`, plus reset time) is the only real Pro-plan signal available. The last one is stored in settings and shown on the Claude meter.

**MCP server** (FastMCP 4.0.11, `apps/api/mcp_server.py`):
- It's mounted inside FastAPI at `/mcp` (streamable HTTP) rather than spawned over stdio. That way it shares the engine's DB, plan service and SSE bus, so a proposed plan appears in the UI immediately.
- `/mcp` is deliberately not under `/api`, so the web proxy never exposes it.
- A per-process random token guards the whole mount at the ASGI level, so only sessions the engine spawned can call it. The first version checked the token only in tools that read the chat id; a live check caught this.
- Tools this phase: `propose_plan`, `list_stories`, `get_story`, `update_story`, `search_memory`, `list_runs`, `get_run`. Adding a tool is one `@tool` function, and the allowlist is derived from it. `source_*`, `extract_from_document` and `save_dossier` come in Phase 6.
- `update_story` applies series/format/notes/hook directly. A **status** change instead creates a plan with a hidden `story_update` step, so it goes through the normal approval (and auto-approve) flow.
- Plan steps accept `"@scout"` as well as `"scout"`. Claude used the `@` form live, and the rejected call cost a turn.

**@mention fast path:** `@scout` / `@outlier` → Groq `parse_mention` → a single-step plan, with no Claude call. It falls back to the orchestrator if parsing fails, the parser picks a different agent, it isn't confident, or the parameters don't validate. The reason is stored on the message and shown under it. `@researcher` says it isn't built yet (Phase 6) without calling anything.

**Results loop:** when an approved plan finishes, the chat gets a result card: per-step summary, top 5 items linking to Stories, Outliers or the run, and YouTube units. It also gets a compact `[engine] Plan #N …` turn so the orchestrator can summarize and suggest next steps.
- In chats that only used @mentions (no Claude session yet), the results aren't sent to Claude right away. They're prepended to the next orchestrator turn instead, so a fast-path run never spends Claude usage on its own.
- Results of `story_update`/`demo` steps never trigger a summary.

**Memory:** `search_memory` = FTS5 (bm25) over messages, stories and dossiers, plus cosine similarity over `embeddings` vectors of the same model as the query vector (NVIDIA first, Gemini fallback via the router). The two rankings are merged with reciprocal rank fusion.
- User, assistant and result messages are embedded in the background after they're saved. A startup backfill covers anything missed.
- The current chat's own messages are excluded, since Claude already has them.
- If embeddings fail, it falls back to keyword search alone and says so (`semantic: false`).

**Claude meter:** each orchestrator turn is a `provider_usage` row (`provider=claude`, duration in `latency_ms`, new `turns` and `chat_id` columns). The meter counts chat turns plus Claude-agent runs per day against a soft cap. The cap defaults to `engine.yaml` `orchestrator.daily_soft_cap` (40), can be overridden in Settings → Agents, warns at 80%, and never blocks. It replaces `providers.yaml` `claude.limits.daily_soft_cap_runs`.

**Browser → API through the web app's origin** (the Phase 4 note): Next.js `rewrites` forward `/api/*` to `127.0.0.1:8000`. `API_BASE` defaults to same-origin, and `NEXT_PUBLIC_API_URL` still overrides it. SSE was verified through the proxy: an event published after connecting arrived over `:3000/api/events`. `compress: false` keeps a future `next start` from gzip-buffering SSE.

**Frontend:**
- Live chat updates are kept in a timestamped overlay that is merged over the last fetch, never written into SWR's cache. A local `mutate()` while a fetch was in flight made SWR discard the fetch: SSE replays recent events right after connecting, which left threads blank and plan cards missing. Both were seen live.
- The app shell now works at phone width: the sidebar opens as a sheet from a top bar, and the Live panel is an overlay below `lg`.
- Plan cards show each step's providers (route order from `providers.yaml`), YouTube estimate and Claude use.
- `lib/mock.ts` now holds only the Research sample (Phase 6).

**Live acceptance (2026-10-06):**
- New chat: "find me 10 fraud stories and check what's working on Company Man" produced **one plan with two steps**: @scout (`mode=both, limit=10, series=Fraud Files`) and @outlier (`channels=@companyman114`).
- Approved, both runs succeeded:
  - @scout: 10 stories, 75 items scored in 46 s, 20 search calls / 40 units.
  - @outlier: 2 units, matching the estimate of 2.
- The orchestrator summarized the results with next steps.
- A **new chat** recalled them through `search_memory` + `list_runs` + `get_run`.
- `@scout 5 news stories about restaurant chains` and `@outlier scan @MagnatesMedia shorts only` each produced a plan card with **no Claude call** (Claude row count unchanged at 5). Both test plans were cancelled.
- Claude usage for all of Phase 5's live testing: 5 calls, 11 turns, 40 s, all on Sonnet.

## Phase 6: @researcher (2026-10-06)

**How it runs:** an approved @researcher step is a job-runner agent (`agents/researcher.py`) that starts `claude -p --agents <json> --agent researcher`.
- The JSON is built from `.claude/agents/researcher.md` (name, description, tools, model) plus the rendered `prompts/researcher.md` as its prompt. This was checked with a Haiku probe: the inline agent's model and prompt apply, and only WebSearch/WebFetch are present among built-in tools.
- Defining the agent inline lets the working directory stay outside the repo, so the project CLAUDE.md isn't loaded. The `.md` file is still the source of truth for the definition.
- Flags beyond the orchestrator's: `--tools WebSearch,WebFetch` (no shell, no file access), `--allowedTools` = researcher MCP tools + WebSearch + WebFetch, `--no-session-persistence`, `--model sonnet --effort medium` (`scoring.yaml` research).

**Turn budgets** (`scoring.yaml` research.depths): quick 20, standard 40, deep 70 Claude turns, where one turn is one model call.
- Each budget is passed as the agent's `maxTurns` and also enforced by the engine. It counts assistant message ids in the stream and stops the process once the budget is exceeded (`stream_claude(max_turns=…)`, shared with chat).
- The prompt states the budget and reserves the last 8 turns for draft, second opinion and save.
- Each run logs one `provider_usage` row (provider `claude`, task `researcher`: turns, duration, tokens), even when it fails. The run summary reports the same.
- The Claude meter now counts every `claude` usage row (chat turns + research runs) instead of adding agent-run counts.

**Separate MCP endpoint for research tools:** `/mcp-research` serves only the researcher's tools, and `/mcp` keeps the orchestrator's 7. Both servers are named `wyrd`, so tool names stay `mcp__wyrd__…`. Splitting them keeps the ~17 research tool schemas out of every chat turn's context; an allowlist alone would still have listed them. Runs pass `X-Wyrd-Run`, and tools use it to find the run's session (`research/session.py`).

**Tools:**
- **One `source_<module>` per sources/ module**, with an `action` parameter where a module has several functions (edgar, wikipedia, wayback, yahoo).
- **Depth limits:** a source outside the run's depth list is refused with a clear message. YouTube is deep-only and capped at 2 searches per run.
- **Known source limits** are logged once per run and listed in the run summary:
  - Yahoo has no data for delisted companies (use EDGAR).
  - GDELT only covers about 3 months.
  - LoC newspapers cover 1770–1963 only; a later start year is refused.
  - EDGAR has no XBRL facts before about 2009.
- **`extract_from_document(url_or_text, question)`** fetches the URL server-side (SEC User-Agent and pacing apply; HTML, PDF via `pypdf`, or text) and keeps the full text in the run session for the excerpt check. It returns only quotes that are literally in the document. Depth `deep` uses the `extract_from_document_deep` route.
- **`second_opinion(dossier)`** runs the router's second opinion (NVIDIA, then Mistral, then Gemini) on a rendered draft. It also runs the excerpt check early, so the researcher can fix failing rows before saving.
- **`save_dossier(dossier)`** refuses until `second_opinion` has been called in the same run.

**Extraction routing by daily headroom** (`providers.yaml` `headroom_tasks`):
- For extraction routes, the model with the largest share of its daily request limit left goes first. Ties keep config order, and models without a daily limit go last.
- The deep route now lists Flash (20/day), then Flash-Lite (500/day), then Mistral and NVIDIA. Flash leads only while it has more headroom than Flash-Lite.
- The existing near-limit and auth-cooldown rules still apply.

**Dossiers are saved as structured JSON, not free markdown** (SPEC said `save_dossier(story_id, markdown, sources_json)`). The researcher submits summary, twist, timeline, people, key numbers, beats, hooks, angles, open questions, numbered sources and second-opinion resolutions. The engine renders the SPEC §6.3 template from that. This makes each fact mechanically checkable, and stores Key Numbers and Timeline as data for v2 @graphics (the Phase 4 note). The DB gains `dossiers.data`, `checks`, `run_id` and `export_path` (migration 0006).

**Integrity checks on save** (`research/dossier.py`):
1. **Excerpt cap:** `excerpt_max_words` (40). Longer excerpts are cut to a prefix, which is still a literal quote.
2. **Excerpt check:** the excerpt must be a substring of the cited source's text after normalization: HTML entities, NFKC, curly quotes, dashes, non-breaking spaces, case, whitespace, and "$ 11,744" → "$11,744". An excerpt with an ellipsis passes if each part of 3+ words appears in order. The source text is what the run already fetched, or the URL is fetched at save time. WebFetch content is never trusted, since it's a summary.
3. **Figure check** (Key Numbers): every non-year number in the figure must appear in its excerpt, by leading significant digits with half-up rounding, so "$11.7 billion" matches "11,744". A figure made only of years must match a year.
4. **Failures:** any Timeline item, Key Number, Twist or person (when cited) that fails is removed from the facts. It is listed under "Open Questions / Unverified" with the reason. A failed Twist becomes "Unverified: see Open Questions."
5. **Primary marking:** sources on `primary_domains` (sec.gov, courtlistener.com, web.archive.org, archive.org, loc.gov, justice.gov, …) are marked primary by the engine, in Sources and `sources.json`. The model's own claim isn't trusted.
6. **Scout hooks** go to the researcher as `scout_hook_UNVERIFIED_LEAD`, and the prompt says to confirm them or leave them out. The check above makes any number in the dossier come from a fetched source.

**Export:** `research/<slug>/dossier.md` and `sources.json` (git-tracked). `sources.json` records, per source, the source type and how many claims were checked and verified. New sources are added to `story_sources` (`added_by=researcher`).

**Story status:** an approved research run moves an Inbox or Shortlisted story to Researching, since approving the plan is the owner's decision. Later statuses are left alone. A topic with no matching story creates one.

**Research page:**
- Real data: dossier list (latest version per story), markdown viewer, version picker, a sources sidebar showing primary sources and per-source verified counts, and the second-opinion flags with their resolutions.
- **Open exported file** asks the API to reveal the file in Finder (`open -R`). It's a local single-user app, and the endpoint only opens the dossier's own export path.
- "Research this" in the story drawer and `@researcher` in Chat both create plan cards. The card shows depth, sources and the Claude turn budget.
- `lib/mock.ts`, `useDemo` and the sample badge are gone; no page uses sample data now.

**Prose number check (added after the live run):** numbers in the Summary, Twist, Story Beats, Hook Ideas and angles must appear in a cited source's text. The match allows filings' "in thousands" tables and the prose's rounding, so "$12.43 billion" matches "12,429,754". Single digits and years are skipped. Unmatched numbers stay in the prose but are listed under Open Questions, and counted separately (`prose_numbers_unverified`). The first live dossier had only the row checks, because its prose included figures (store and employee counts) that no row covered. A dry run of the new check on that dossier found all of them in cited sources.

**Unreadable links fail fast:**
- Google News results are redirect wrappers the engine can't fetch, and the researcher wasted a turn on one. `extract_from_document` now refuses them up front, with a note to use the publisher's URL.
- CourtListener docket pages return 403 to plain fetches; this now gives a clear note too.

**Live acceptance: standard-depth Circuit City (run #10, 2026-10-06):**
- Started from Chat with `@researcher Circuit City, standard depth`. The fast path made the plan card with no Claude call; it showed depth, sources and the 40-turn budget.
- **Claude:** 34 of 40 turns, 393 s, 432K tokens in / 17.6K out, Sonnet. The run log has one usage row (`task=researcher`).
- **Tool calls:** 13 extractions, 9 EDGAR, 3 news, 2 Wikipedia, and one each of CourtListener, Internet Archive, Wayback, Yahoo, second opinion and save.
- **Extraction:** the FY2008 and FY2007 10-Ks (~326K characters each) went through `extract_from_document`, giving 7 and 5 exact quotes. The FY2006 10-K gave none.
- **Dossier v1** has 17 Timeline items, 8 Key Numbers, 5 Key People and 5 sources, 4 of them primary (two 10-Ks, two 8-Ks).
- **Excerpt check:** 31 passed, 1 moved to Open Questions. The failure was the Blockbuster bid row: after the second opinion's pre-check failed it, the researcher "fixed" it with wording that isn't literally on the page, and the check on save caught it. An independent re-check of all 31 against freshly fetched sources passed 31/31. The longest excerpt is 36 words.
- **Second opinion** (NVIDIA): 7 flags, 0 high. They were resolved as 4 softened ("#2 retailer" claims, causal language), 1 removed (CarMax market value), 1 rewritten (the "60 days" hook), and 1 fixed (the Blockbuster excerpt, which was then moved by the check).
- **Exported** to `research/circuit-city/`, and viewable on the Research page.
- **Source notes:** Circuit City has no EDGAR XBRL facts (pre-2009), so financials came from the 10-K text. One Google News link and one CourtListener docket page couldn't be fetched (the fail-fast notes above came from this).

## Phase 6 review fixes (2026-10-06)

**Claim-vs-excerpt support check:** an excerpt that exists in the source can still be stretched by its claim (v1 said "highest-paid hourly" where the excerpt says "better-paid").
- New router task `check_support` (`prompts/claim_support.md`): Groq `gpt-oss-120b` first, NVIDIA as fallback. Groq's 20B model wrongly called a date in an excerpt unsupported during testing, so the larger model is primary.
- It asks whether the excerpt supports every factual part of the claim, for Timeline items, Key Numbers, Key People and the Twist, but only rows that already passed the excerpt check.
- Unsupported details are trimmed when what's left still stands (and the trim is noted in Open Questions). Otherwise the row moves to Open Questions.
- If every provider fails, rows are kept on the excerpt check alone and the dossier records "support check unavailable". The check runs in the second-opinion pre-check and again on save.
- Observed: when Groq hits its 8K tokens/minute limit, NVIDIA takes over and is noticeably more lenient (0 trims where Groq trimmed 3 on the same rows). The checker that ran is in `provider_usage`.

**Prose numbers:**
- Spelled-out numbers are converted to digits for checking ("eighteen" → 18).
- Spans like "N days/weeks/months/years (later)" and "N-year-old" must match the gap between two dated Timeline items. The rounded gap must equal N, or be within ±1 with "about/nearly/over…". These spans are excluded from the plain number check.
- Timeline dates are parsed from YYYY[-MM[-DD]], "Nov 2008" and "November 10, 2008". A year-only date can only anchor gaps measured in years.
- Known limit: the check can't tell which two events the prose means. Any matching pair of dates passes.

**Interpretation stated as fact:**
- The second opinion now classifies each flag (`unsupported`, `interpretation`, `superlative`, `defamation`, `weak_source`) and reviews the prose sections too. It's told not to list fine claims, or labelled interpretations that are acceptable as written.
- `save_dossier` refuses while there are fewer `second_opinion_resolutions` than interpretation or high-severity flags. The new resolution action is `labelled_interpretation`.
- The researcher prompt says interpretations must read "Our read: …" or go to Open Questions.
- NVIDIA still flags some labelled interpretations; these are resolved as `labelled_interpretation`.

**Circuit City v2** (v1 kept in history), built from v1 with the owner's fixes, each sourced:
- Bankrupt "about 19 months" after the layoffs (Mar 28, 2007 → Nov 10, 2008).
- Revival reported January 2016; online relaunch August 22, 2018.
- The Blockbuster April 2008 bid ($1B–$1.3B), in Wikipedia's wording.
- 712 Superstores + 9 outlet stores at **October 31, 2008**, from the Nov 10, 2008 8-K. The brief said "before closures"; the 8-K dates the count October 31.
- 654 = FY2007 total stores (642 Superstores + 12 others).
- 43,011 domestic employees at Feb 28, 2007 (FY2007 10-K).
- 155 closings announced Nov 4, 2008; Chapter 11 filed Nov 10.
- CarMax "spun off to shareholders".
- "Best Buy drove Circuit City into bankruptcy" labelled as interpretation and listed in Open Questions.
- Unsourced "missing the housing boom" and "customer service deteriorated" moved to Open Questions.
- Layoff rows reworded to match "better-paid associates".
- 10-K table excerpts now include the "(Amounts in thousands …)" header, and the net loss uses the 10-K's own sentence.

Results: 41/41 claims pass the excerpt check, the support check (Groq 120B) makes 0 trims and 0 moves, and no prose number is unverified.

**1988 Best Buy offer:** Wikipedia cites Alan Wurtzel's 2012 memoir *Good to Great to Gone* (p. 215), which is first-hand but not contemporaneous. Searches turned up no 1988–89 source: Internet Archive full-text, web search, and a 2013 Richmond Fed *Econ Focus* article, which covers the Best Buy rivalry but not the offer. LoC newspapers stop at 1963. The offer stays in the dossier as "reportedly", with an Open Question.

## Phase 7: Notion sync (2026-10-06)

**API:** `Notion-Version: 2026-03-11`, the latest version as of 2026-10-06 (developers.notion.com/reference/versioning).
- A database has data sources. The engine reads `data_sources[0].id` from `GET /v1/databases/{id}`, creates pages with `parent: {type: "data_source_id"}`, and lists them with `POST /v1/data_sources/{id}/query` (100 per page, cursor pagination).
- `archived` is now `in_trash`.
- No SDK: a small httpx client (`notion_sync.py`), so the version header is under our control.

**Rate limit:** Notion allows about 3 requests/s per connection (non-Enterprise), with a separate workspace budget.
- Requests are paced at least 0.4 s apart (`engine.yaml` notion.min_interval_s).
- On a 429 the client waits at least `Retry-After`, then backs off exponentially with jitter. 5xx and network errors retry too (`max_retries` 4).
- The last report counts the requests each sync made.

**Database:** "wyrd.exe Stories", created once with the Notion connector (owner's account, private, workspace top level).
- Properties: Title (title); Status, Series and Format (select, with the engine's values as options); Hook, Scores, Sources and Notes (text); Gap Score and Engine ID (number); Updated (date).
- `Engine ID` maps pages back to stories, in addition to `stories.notion_page_id`.
- Status is a **select**, not Notion's Status type, so the 9 engine statuses map one-to-one.
- Before every sync the engine checks these property names and types, and stops with a list of differences if they don't match.
- The app itself only uses `NOTION_TOKEN` and `NOTION_DATABASE_ID`. The integration must be added to the database (••• → Connections).

**Push** (on Sync now, or a few seconds after a story change when auto-sync is on):
- Pushes Title, Status, Series, Format, Hook, Scores, Gap Score, Sources, Updated, plus Notes and Engine ID.
- A story is pushed when it has no page yet or `updated_at > notion_synced_at`; unchanged stories cost no requests.
- A page deleted in Notion is recreated.
- Every Hook starts with `UNVERIFIED LEAD:`, the same rule as the UI badge (hooks are LLM-written; facts come from dossiers).
- Text is cut to Notion's 2000-character limit.

**Pull** (Status and Notes only), run before the push on every full sync:
- Notion's `last_edited_time` only has minute precision, so changes are detected by value. After a push, Notion holds exactly what was pushed, so a different Status/Notes value means it was edited in Notion.
- If the story didn't change locally since the last sync, Notion's value is applied. If both changed, the newer of `last_edited_time` and `updated_at` wins.
- A pulled change sets `updated_at = notion_synced_at = now`, so it isn't pushed straight back. It publishes `story.changed` with `source: notion`, which the auto-sync watcher ignores.
- A Notion status that isn't one of the 9 engine statuses is ignored and reported. Pages without an Engine ID (added by hand in Notion) are ignored and counted.
- Known edge: if both sides change within the same minute, the minute-rounded Notion time can lose to the local edit.

**Auto-sync** (Settings toggle, stored in the settings table, off by default) pushes about 5 s after the last story change and runs a full sync every 10 minutes. Sync isn't an agent, so it doesn't go through plan approval; it only mirrors data and only Status/Notes come back.

**No token:** the service reports `configured: false`, Sync now returns 409, and the auto-sync watcher does nothing. Nothing else depends on Notion; a test runs the API with no Notion settings.

**Also fixed:** the Research page's live refresh listened for `dossier.saved`, but that event wasn't in the SSE listener list, so it never fired.

**Live acceptance (2026-10-07):**
- **First Sync now:** created all 25 stories in "wyrd.exe Stories" in 28 requests over 11.9 s (paced). The connector confirmed every row: hooks prefixed `UNVERIFIED LEAD:`, Scores, "N sources (P primary)", Notes and Engine ID.
- **Notion → app:** in Notion (via the connector), story #20 (FTX) Status went Inbox → Shortlisted and story #25 (Circuit City) got a new Note. The next sync pulled both (1 request, schema check cached), and the app showed the new Status and Notes. Neither was pushed back.
- **App → Notion:** reverting both in the app then syncing updated 2 pages (recorded as local-won conflicts, correctly), and Notion showed the original values again.

## Fallback support checks (2026-10-07)

The claim-support checker's fallback (NVIDIA) is more lenient than Groq.
- `Router.check_support` now returns a `SupportResult` with `served_by` (provider/model of every batch), `primary` (the route's first configured step) and `fallback`. Anything other than the primary counts as a fallback. That includes NVIDIA answering first because the router moved a near-limit Groq to the back of the route; the router's own "fallback" flag misses that case.
- A dossier checked by a fallback records `checks.support_checked_by`. Its markdown header says the check "ran on a fallback model …; re-check with Groq". The Research page shows a **checked by fallback** badge and a **Re-check with Groq** button.
- `POST /api/dossiers/{story_id}/recheck` re-runs every check on the latest version with Groq pinned (`primary_only`, no fallback) and saves the result as a new version, carrying the second-opinion review over with `recheck_of_version`.
- If Groq can't run (rate limit or outage), it returns 503 and saves nothing.

## Claude agent outage: root cause and status check (2026-10-16)

**Symptom:** chat (orchestrator) and @researcher stopped working after 2026-10-07; @mention fast paths kept working.

**Root cause: the Claude Code CLI really was logged out.** The engine's check was right; its message just didn't show any evidence. Timeline (UTC):
- 02:35, last successful Claude call (fast-path outlier plan; the last @researcher run was on 10-06).
- 21:57:31, the real `claude -p` turn for chat #5 already failed with "Not logged in · Please run /login".
- 21:57:43, the CLI rewrote its macOS keychain item (`Claude Code-credentials`).
- 21:59:07, the startup check (`claude auth status --json` → `loggedIn: false`, exit 1) blocked the next turn.

The stored login stopped working on the Claude side (expired or revoked, and the CLI cleared it). Nothing in the repo changed it.

**Ruled out:**
- **A CLI update changed the status format.** The binary (`/opt/homebrew/bin/claude` → npm `@anthropic-ai/claude-code`, 2.1.196) hasn't changed since 2026-06-30, and `auth status --json` still prints `loggedIn`/`authMethod`.
- **A different environment under `make dev`.** The API process logs `claude cli: /opt/homebrew/bin/claude · 2.1.196 · state=logged_out · HOME=/Users/rei`, which matches a clean `env -i` shell and an unsandboxed one. There is only one install and no `CLAUDE_CONFIG_DIR`.
- **Keychain access denied.** Every environment I tried reported the same logged-out state, and the keychain item itself is readable.

**Fix:** `claude auth login` (owner). The engine changes below make the next failure explain itself.

**Status check changes (`apps/api/system.py`):**
- `ClaudeStatus.state` is one of `ready`, `logged_out`, `unknown` or `not_installed`.
- Stdout and stderr are captured separately, and the JSON object is found even with warnings around it.
- If `--json` stops working, the check asks `claude auth status` in plain text.
- Output the check can't read is `unknown`, never "logged out".
- Chat blocks only on a definite `logged_out`/`not_installed` (`ClaudeStatus.usable`). On `unknown` it makes the real call and shows that call's error.
- The status carries the CLI's own output: trimmed to 400 chars, with emails, `sk-ant-…` tokens and long opaque ids redacted.
- It also carries the `claude` path. The API logs path, version, state and HOME at startup through uvicorn's logger; app loggers aren't configured, so their INFO lines don't print.

**UI:**
- Settings › Agents › Claude card: CLI status, version, and **Re-check** (a fresh check). When not ready, it shows `$ claude auth status --json` and what the CLI printed.
- The top banner and the Settings › System row show the same output, with a link to Re-check.

**Tests:** `tests/test_system.py` covers:
- the real 2.1.196 logged-out output;
- logged in;
- logged in with a stderr warning;
- unknown formats (empty, timed out, renamed key, `--json` rejected, new text) → `unknown`;
- the plain-text fallback;
- redaction.

`tests/test_chat.py` checks that an `unknown` status still calls Claude.

**Dev:** `.claude/launch.json` gains an `api` entry (`make api`) so the API can be started from the preview tools.

**Live verification after `claude auth login` (2026-10-16):**
- **Settings › Claude:** Re-check showed **ready · 2.1.196 (Claude Code)**, and the banner cleared.
- **Orchestrator:** a plain chat message ("Find 5 new Fraud Files story ideas from recent news.", chat #6) got a reply in 4.6 s, and its `propose_plan` call produced plan card #14 (@scout news, limit 5). The plan was left pending, not run.
- **@researcher:** `@researcher Bre-X, quick depth` → plan #15 approved → run #12 succeeded in 9 m 38 s, 14/20 Claude turns. It saved `research/bre-x/dossier.md` v1 with 22/22 excerpts verified. The support check ran on Groq (primary, not a fallback): 5 trimmed, 0 moved.
- **Seen during the run, not part of this fix:**
  - NVIDIA timed out three times, so the second opinion was unavailable (the save goes ahead, as designed).
  - One `extract_from_document` call failed on every provider (NVIDIA returned invalid JSON). Claude retried with another page.

## Re-running a dossier's second opinion; NVIDIA timeout (2026-10-16)

- **Why:** the Bre-X dossier (run #12) saved without a second opinion: NVIDIA "timed out" three times, Mistral has 0 quota and the Gemini OAuth login had expired.
- **NVIDIA wasn't down:**
  - A one-word request answered in 0.6 s.
  - The full second opinion (3.4k prompt tokens, a long JSON reply) ran at about 32 tokens/s and needed more than 60 s, the adapter's hardcoded HTTP timeout.
  - The HTTP timeout is now configurable per provider (`timeout_s` in `config/providers.yaml`); NVIDIA is set to 150 s and every other provider keeps the 60 s default.
- **`rerun_second_opinion` / `POST /api/dossiers/{story_id}/second-opinion`** re-runs only the review on the latest version.
  - Claims don't change, so it updates the same version (no new one): new `flags` and `overall`, `rerun: true`, the earlier outcome under `previous`, and earlier resolutions kept.
  - If no provider answers, it returns 503 and changes nothing.
  - New flags are left for the owner or a new research run to resolve; the engine doesn't edit claims.
- **Bre-X result (NVIDIA, about 2 min):** 50 flags.
  - 30 low: mostly "unsupported" on rows the excerpt check had verified. The reviewer sees only the dossier, not the sources.
  - 20 medium/high interpretation/superlative flags in Summary, Story Beats, Hook Ideas and Angles: "largest mining fraud in history", "mastermind", "Suharto forced", "Canada overhauled its rules to prevent a repeat", and a hook with an unsourced "river dust and a syringe".
  - These are unresolved on v1; the owner decides how to fix them.

## Provider cleanup for the demo (2026-10-16)

- **Mistral disabled.** `enabled: false` (new `ProviderConfig.enabled`, default true) in `config/providers.yaml`.
  - Routes keep their Mistral steps; the router skips them with a "disabled in providers.yaml" event and no run-log warning.
  - `request_budget` ignores Mistral.
  - The connection test, `/api/keys`, `/api/providers` and the usage meters report `disabled`, which isn't an error. Settings shows it struck through in task routing.
- **OpenRouter `long` alias** (`nvidia/nemotron-3-super-120b-a12b:free`, 262K context, 200K request budget) is the last fallback for `extract_from_document`, `extract_from_document_deep` and `analyze_outliers`.
  - The existing `free` alias (Gemma 4 31B, 32K budget) wasn't reused: adding it would have shrunk every extraction chunk to 32K, since the route takes the smallest budget.
  - Gemma 4 31B `:free` (262K) was rate-limited upstream when tested.
  - Nemotron answered a live extraction in 11 s with valid JSON. It's the same model family as the NVIDIA fallback, but reached through OpenRouter with its own quota.
  - Two aliases can now share a model ID; the usage meter counts that model once.
- **Gemini OAuth expiry:** Google expires refresh tokens after 7 days only for apps in **Testing**. Publishing ("In production") removes that limit. Our scopes are sensitive, so without verification Google shows an "unverified app" warning (under the 100-user cap), which is fine for a personal tool. Steps are in the demo-prep report.
