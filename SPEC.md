# wyrd.exe Story Engine — Build Spec

**Owner:** wyrd.exe (faceless YouTube channel: true business stories told like thrillers)
**Builder:** Claude Code
**Version:** 1.0 (v1 scope: orchestrator, @scout, @outlier, @researcher)

---

## 1. Purpose

The story engine removes the channel's biggest bottleneck: **finding, reading, and researching stories.** The owner's time should go to narration and editing. The engine finds story candidates, identifies proven topics on YouTube, and produces sourced research dossiers ready for scripting.

It is a **local app** (runs on the owner's computer) with a polished web interface, a chat-based **orchestrator** that manages specialized agents, and a dashboard showing live agent activity and API quota usage.

## 2. Core principles

1. **Claude is the manager, free models are the workers.** The orchestrator and @researcher use Claude (via Claude Code headless, covered by the owner's Claude Pro plan). High-volume or long-document work goes to free APIs (Groq, Gemini, NVIDIA). Claude never reads raw long documents when Gemini can extract from them first.
2. **Nothing runs without approval.** Every agent run is proposed as a plan card. The owner approves, edits, or cancels. (Per-agent auto-approve toggles exist in Settings but default to OFF.)
3. **Every fact has a source.** Research output must link each factual claim to a URL and a supporting excerpt. No invented numbers, quotes, or dates.
4. **Config over code.** Model IDs, rate limits, source lists, and thresholds live in config files editable from Settings. Free-tier models and limits change often.
5. **Graceful failure.** Every provider call goes through a router with retries and fallbacks. One API failing never crashes a run.
6. **Local and private.** Backend binds to 127.0.0.1 only. Secrets live in `.env` (never committed).

## 3. Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui |
| Font / feel | Geist Sans + Geist Mono; Linear/Vercel-style dark UI |
| Backend | Python 3.11+ with FastAPI |
| Python tooling | `uv` for dependencies; `ruff` for lint; `pytest` for tests |
| JS tooling | `pnpm`; ESLint; TypeScript strict mode |
| Database | SQLite (WAL mode) via SQLModel/SQLAlchemy, with FTS5 for full-text search |
| Jobs | DB-backed job queue running in the FastAPI process (asyncio). No Redis. |
| Live updates | Server-Sent Events (SSE) from backend to frontend |
| Agent runtime | Claude Code CLI in headless mode (`claude -p ...`), spawned by the backend |
| Agent tools | A local MCP server (Python, FastMCP) exposing the engine's tools to Claude |
| App install | PWA manifest so the owner can "Install app" from Chrome/Edge for a desktop-app feel |

**Repo layout**

```
story-engine/
├── CLAUDE.md
├── SPEC.md
├── .env.example
├── Makefile                  # make setup, make dev, make test
├── config/
│   ├── providers.yaml        # model IDs, rate limits, fallbacks per task
│   ├── sources.yaml          # scout feeds, queries, wikipedia categories
│   ├── channels.yaml         # competitor channels for @outlier
│   └── scoring.yaml          # thresholds and rubric weights
├── prompts/                  # all LLM prompts as .md files (no prompts hardcoded in code)
│   ├── orchestrator.md
│   ├── scout_scoring.md
│   ├── outlier_analysis.md
│   ├── researcher.md
│   ├── doc_extraction.md
│   └── second_opinion.md
├── .claude/agents/
│   └── researcher.md         # Claude Code subagent definition
├── apps/
│   ├── web/                  # Next.js frontend
│   └── api/                  # FastAPI backend
│       ├── main.py
│       ├── db/               # models, migrations, FTS setup
│       ├── providers/        # groq.py, gemini.py, nvidia.py, router.py, usage.py
│       ├── sources/          # edgar.py, yahoo.py, youtube.py, wikipedia.py, wayback.py,
│       │                     # courtlistener.py, loc_newspapers.py, internet_archive.py,
│       │                     # news_rss.py, hackernews.py, reddit_rss.py, gdelt.py
│       ├── agents/           # scout.py, outlier.py, researcher.py, orchestrator.py
│       ├── mcp_server.py     # exposes tools to Claude Code
│       ├── jobs.py           # queue, runner, cancellation
│       ├── notion_sync.py
│       └── exporters.py      # markdown export of dossiers
├── research/<story-slug>/    # exported dossier.md + sources.json (git-tracked)
└── data/wyrd.db              # SQLite database (git-ignored)
```

## 4. Free API roster and roles

All endpoints, SDKs, model IDs, and limits must be **verified against current official docs** before implementation. Values below are starting points.

| Provider | Role | Notes |
|---|---|---|
| **Claude (Claude Code headless)** | Orchestrator brain; @researcher reasoning and writing | Uses owner's Pro plan; has usage limits, so use sparingly |
| **Groq** (free tier, OpenAI-compatible API) | Fast, high-volume tasks: scoring headlines, parsing @mention params, classifying, short summaries | Very fast; strict per-minute limits |
| **Google Gemini** (free tier, `google-genai` SDK) | Long-document reading: 10-Ks, court filings, long articles, Wikipedia pages; outlier pattern analysis | Huge context window |
| **NVIDIA** (build.nvidia.com, OpenAI-compatible API) | Second-opinion review of dossiers; embeddings for semantic dedup and memory search | Free credits; track usage |
| **SEC EDGAR** (official, free) | Primary financials (XBRL company facts), filings, full-text search | Requires User-Agent header with name + email; respect ~10 req/sec |
| **Yahoo Finance** (`yfinance`, unofficial) | Stock price history and market cap context | Unofficial and can break; always secondary to EDGAR; fail gracefully |
| **YouTube Data API v3** (free quota) | @outlier channel/video stats; coverage checks for gap finder | 10,000 units/day; prefer `playlistItems.list` and `videos.list` (1 unit) over `search.list` (100 units) |
| **Wikipedia / Wikimedia** | Category crawling, article text, pageview stats | MediaWiki API + Wikimedia REST pageviews API |
| **Wayback Machine** (CDX API) | Historical snapshots of company websites | Free |
| **CourtListener** | Lawsuits, bankruptcy dockets | Free token |
| **Library of Congress** (Chronicling America / loc.gov) | Historical newspapers | Verify current endpoint (service has been migrating) |
| **Internet Archive** | Old annual reports, magazines, ads, films | Free |
| **Google News RSS** | Breaking business news via saved queries | Free RSS |
| **Hacker News** (Algolia API) | Tech/startup stories | Free |
| **Reddit** (subreddit RSS) | Story leads | Use RSS, not the authenticated API |
| **GDELT** (DOC API) | Global news search by keyword | Free |
| **Notion API** | Optional sync of the story pipeline | Free integration token |

### 4.1 Provider router

`providers/router.py` exposes task-level functions, not provider-level ones:

```
score_items(items) -> scores          # primary: Groq   fallback: Gemini → NVIDIA
parse_mention(text) -> agent, params  # primary: Groq   fallback: Gemini
extract_from_document(doc, question)  # primary: Gemini fallback: NVIDIA
analyze_outliers(videos)              # primary: Gemini fallback: Groq
second_opinion(dossier)               # primary: NVIDIA fallback: Gemini
embed(texts)                          # primary: NVIDIA fallback: Gemini embeddings
```

- Task → provider mapping comes from `config/providers.yaml`.
- Retries with exponential backoff on 429/5xx; on repeated failure, fall back to the next provider and log it.
- All LLM calls that return data use JSON mode / structured output, validated with Pydantic. Invalid JSON gets one repair retry.
- Every call is logged to `provider_usage` (provider, model, task, tokens in/out, latency, success, timestamp).

### 4.2 Quota tracking

- `config/providers.yaml` holds each provider's known free-tier limits (requests/min, requests/day, tokens/day, YouTube units/day). Editable in Settings because limits change.
- The router checks remaining budget before calling and prefers fallbacks when a provider is near its limit.
- **Claude usage:** exact Pro plan usage isn't available programmatically. Track Claude runs locally (count, duration, turns) and show them as a meter with a configurable daily soft cap.

## 5. The orchestrator

### 5.1 Behavior

- The owner chats with the orchestrator in the Chat page. It is a Claude Code headless session given `prompts/orchestrator.md` as its system prompt and connected to the local MCP server.
- It understands the agents, their parameters, and the story database. It answers questions directly when no agent is needed ("What stories do we have in Fraud Files?").
- When work is needed, it **must** call the `propose_plan` tool instead of running anything. The plan is saved as pending and rendered as a plan card. Execution only happens after the owner approves.
- After agents finish, the backend feeds results back into the same chat so the orchestrator can summarize and suggest next steps.

### 5.2 @mentions

- Messages starting with `@scout`, `@outlier`, or `@researcher` bypass the orchestrator: Groq parses the parameters, and the backend creates a single-step plan card directly. This saves Claude usage.
- If parsing fails or the request is ambiguous, fall back to sending it to the orchestrator.
- The chat input has @-autocomplete listing agents with one-line descriptions.

### 5.3 Plan cards

- Show each step: agent, parameters, which providers it will use, estimated YouTube quota cost (for @outlier and gap finder), and whether it uses Claude.
- Buttons: **Approve**, **Edit** (edit parameters inline as a form), **Cancel**.
- Settings has per-agent "auto-approve" toggles, default OFF for all.

### 5.4 Memory

- All chats and messages are stored in SQLite.
- Each chat thread maps to a Claude Code session; continue it with the CLI's resume option so context carries over.
- Cross-chat memory: the MCP server exposes `search_memory(query)` (FTS5 + NVIDIA embeddings over past messages, stories, and dossiers) and `get_story(id)`, so the orchestrator can recall past work in any new chat.
- Keep the orchestrator's context small: it fetches memory on demand rather than loading everything.

### 5.5 MCP tools exposed to Claude

| Tool | Purpose |
|---|---|
| `propose_plan(steps, summary)` | Create a pending plan for approval |
| `list_stories(filters)` / `get_story(id)` / `update_story(id, fields)` | Story database access (updates also require plan approval if they change status) |
| `search_memory(query)` | Search past chats, stories, dossiers |
| `get_run(id)` / `list_runs(filters)` | Inspect agent runs and results |
| `source_*` tools | Wrappers over every module in `sources/` (used by @researcher) |
| `extract_from_document(url_or_text, question)` | Sends long docs to Gemini, returns extracts with exact quotes |
| `save_dossier(story_id, markdown, sources_json)` | Save research output |

## 6. Agents (v1)

Each agent is a job: it has typed parameters, streams logs to the UI over SSE, can be cancelled, and writes results to the database.

### 6.1 @scout — story discovery

**Params:** `mode` (news | evergreen | both), `topic` (optional free text, e.g. "fraud", "restaurants"), `limit` (default 25), `series` (optional).

**News mode**
1. Pull items from Google News RSS saved queries, SEC and DOJ press release feeds, EDGAR full-text search, Hacker News, subreddit RSS, and GDELT (all defined in `config/sources.yaml`).
2. Normalize to `{title, url, source, published_at, snippet}`.
3. Dedupe: exact URL hash, then NVIDIA embeddings against existing stories and other items (cosine similarity threshold in `scoring.yaml`).
4. Groq scores items in batches using `prompts/scout_scoring.md`.

**Evergreen mode ("gap finder")**
1. Crawl configured Wikipedia categories (e.g. defunct companies, companies that filed for Chapter 11, corporate scandals).
2. For each article: length, number of references, 60-day pageviews.
3. Pre-score with Groq; take the top N (configurable, default 20) for a YouTube coverage check: one `search.list` call each, count videos above a view threshold about that company's story.
4. **Gap score** = high story quality + rich article + low existing YouTube coverage.
5. Respect the YouTube quota budget; show estimated units on the plan card.

**Scoring rubric (1–10 each, JSON output):** drama, twist, relatability to 25–35-year-olds, visual potential, hook number (a striking figure), freshness (not already overdone). Also return: one-line hook, suggested series (Childhood Brands, Tech Graveyard, Fraud Files, Everyday Genius, Comebacks, Recent Collapses), and suggested format (Short or Long).

**Output:** stories saved with status `Inbox`, scores, and source links. Summary posted to chat.

### 6.2 @outlier — YouTube outlier research

**Params:** `channels` (default: all in `channels.yaml`), `videos_per_channel` (default 50), `threshold` (default 3.0), `format` (shorts | long | both).

1. Resolve channel handles to IDs (`channels.list` with handle lookup), cache IDs.
2. Fetch recent uploads via the uploads playlist, then stats via `videos.list` (batches of 50).
3. Classify Shorts vs long-form by duration (Shorts can be up to 3 minutes; verify current rule) and compute medians **separately** for each format.
4. Outlier score = views ÷ channel median for that format. Flag videos ≥ threshold.
5. Gemini analyzes flagged videos with `prompts/outlier_analysis.md`: topic, company type, hook/title pattern, why it likely worked, and a suggested wyrd.exe angle.
6. Optionally create story candidates from outlier topics (status `Inbox`, tagged `from_outlier`).

**Seed channels (`channels.yaml`):** Company Man, Modern MBA, Magnates Media. Owner adds more in Settings.

**Output:** outlier records, a report in the run view, a summary in chat.

### 6.3 @researcher — deep research + primary sources

**Params:** `story_id` or `topic`, `depth` (quick | standard | deep), `focus` (optional, e.g. "the 2007 layoffs").

Runs as a Claude Code headless subagent (`.claude/agents/researcher.md`) connected to the MCP server, with a restricted tool allowlist (MCP tools, web search, web fetch; no shell commands that modify files outside `research/`).

1. Plan research questions (timeline, key people, key numbers, the twist, the aftermath).
2. Gather primary sources first: EDGAR filings and XBRL facts, court records, Wayback snapshots of the company site, historical newspapers, Internet Archive documents. Then reputable secondary sources.
3. Send long documents to `extract_from_document` (Gemini) instead of reading them in full.
4. Use Yahoo Finance for stock-price context (secondary to EDGAR).
5. Write the dossier (template below).
6. Run `second_opinion` (NVIDIA) to flag unsupported or shaky claims; fix or mark them.
7. `save_dossier` → stored in DB and exported to `research/<slug>/dossier.md` + `sources.json`.

**Dossier template**

```
# <Company/Story> — Research Dossier
Summary (one paragraph)
The Twist (the single most surprising fact)
Timeline (dated bullet list)
Key People
Key Numbers (table: figure | meaning | source URL | supporting excerpt)
Story Beats (rise → peak → cracks → fall/comeback → aftermath)
Hook Ideas (5)
Best Angle for a Short / Best Angle for Long-form
Open Questions / Unverified (anything not confirmed)
Sources (numbered, primary sources marked)
```

**Rules:** every claim in Key Numbers and Timeline must have a source URL and excerpt. Unconfirmed items go only in "Open Questions / Unverified." Respect copyright: excerpts are short supporting snippets, not long passages.

### 6.4 Reserved for v2 (design for, don't build)

- `@factcheck`: claim extraction + verification against dossier sources.
- `@graphics`: reads `[GRAPHIC]` cues from scripts and renders Remotion templates.
- Scheduled runs (local cron and/or GitHub Actions).

The agent registry should make adding these a matter of adding one module + one config entry.

## 7. Data model (SQLite)

| Table | Key fields |
|---|---|
| `stories` | id, slug, title, company, status (Inbox, Shortlisted, Researching, Scripting, Fact-check, Recording, Editing, Published, Archived), series, format, hook, scores (JSON), gap_score, outlier_ref, notes, created_at, updated_at, notion_page_id, notion_synced_at |
| `story_sources` | id, story_id, url, title, source_type (primary/secondary), excerpt, added_by |
| `dossiers` | id, story_id, version, markdown, sources_json, second_opinion (JSON), created_at |
| `channels` | id, handle, channel_id, name, uploads_playlist_id, last_scanned_at |
| `videos` | id, channel_id, video_id, title, published_at, duration_s, is_short, views, likes, comments, outlier_score, analysis (JSON) |
| `chats` | id, title, claude_session_id, created_at, updated_at |
| `messages` | id, chat_id, role (user/assistant/system/agent), content, metadata (JSON), created_at |
| `plans` | id, chat_id, status (pending/approved/cancelled/done/failed), summary, created_at, decided_at |
| `plan_steps` | id, plan_id, order, agent, params (JSON), status, run_id |
| `agent_runs` | id, agent, params (JSON), status (queued/running/succeeded/failed/cancelled), started_at, finished_at, result (JSON), error |
| `run_logs` | id, run_id, ts, level, message, data (JSON) |
| `provider_usage` | id, provider, model, task, tokens_in, tokens_out, units, latency_ms, ok, ts |
| `settings` | key, value (JSON) |
| `embeddings` | id, ref_type, ref_id, vector (blob), model |

FTS5 virtual tables over `messages.content`, `stories` (title, hook, notes), and `dossiers.markdown`.

## 8. Notion sync

- Local SQLite is the source of truth. Notion is an optional mirror for viewing on phone or sharing.
- Sync the `stories` table to a Notion database (fields: Title, Status, Series, Format, Hook, Scores, Gap Score, Sources, Updated).
- Push: create/update Notion pages on demand ("Sync now" button) and after story changes if auto-sync is enabled.
- Pull: only the **Status** and **Notes** fields come back from Notion (so the owner can move cards on mobile). Conflicts resolve by most recent `updated_at`.
- Sync is entirely optional: the app works fully with no Notion token.

## 9. Interface

**Style:** Linear/Vercel-like. Near-black background, subtle 1px borders, generous spacing, Geist fonts, one accent color (suggest a violet or electric blue; make it a theme token). Smooth but restrained animations. Keyboard-first: `Cmd/Ctrl+K` command palette (jump to pages, start an agent, search stories). Brand mark: `wyrd.exe` in Geist Mono in the sidebar.

**Layout:** left sidebar (Home, Chat, Stories, Research, Outliers, Settings), main content area, and a collapsible right panel for live run logs available on every page.

**Pages**

1. **Home (dashboard)**
   - **Live agent activity:** running and recent runs with status, elapsed time, current step, and a streaming log tail. Click a run to open its detail view.
   - **API usage and quota meters:** one card per provider showing today's usage vs. limit (requests, tokens, or YouTube units), fallback events, error rate, plus the Claude runs meter with the soft cap.
   - Small "pending approvals" strip linking to unapproved plan cards.
2. **Chat**
   - Thread list on the left; conversation in the center; streaming responses.
   - @-autocomplete for agents. Plan cards inline with Approve / Edit / Cancel.
   - Agent results appear inline as compact result cards (e.g. "Scout found 18 stories, top 5: …") linking to full views.
3. **Stories**
   - Table view (default) with sorting and filters (status, series, format, score), and a toggle to a board view grouped by status with drag-and-drop.
   - Story detail drawer: scores, hook, sources, dossier versions, actions ("Research this," "Move to Shortlisted").
4. **Research**
   - List of dossiers; markdown viewer with a sources sidebar; version history; "Copy for Script Room" and "Open exported file" buttons.
5. **Outliers**
   - Table of flagged videos (channel, title, format, views, outlier score, Gemini analysis); filter by channel and format; "Create story from this" action.
6. **Settings**
   - API keys status (set / missing / failing, with a "Test connection" button per provider; keys themselves are read from `.env`, never displayed in full).
   - Provider routing and model IDs (editable `providers.yaml` values), quota limits, Claude soft cap.
   - Per-agent auto-approve toggles (default OFF).
   - Scout sources and Wikipedia categories; competitor channels for @outlier; scoring thresholds.
   - Notion sync settings.

**PWA:** include a manifest and icons so the app can be installed as a desktop app from the browser.

## 10. Running the app

- `make setup`: installs Python deps (uv) and JS deps (pnpm), creates the database, copies `.env.example` to `.env` if missing.
- `make dev`: starts FastAPI (127.0.0.1:8000) and Next.js (127.0.0.1:3000) together.
- `make test`: runs pytest and frontend type checks/lint.
- The backend checks on startup that the `claude` CLI is installed and logged in, and shows a clear banner in the UI if not.

**`.env.example`**

```
GROQ_API_KEY=
GEMINI_API_KEY=
NVIDIA_API_KEY=
YOUTUBE_API_KEY=
COURTLISTENER_TOKEN=
NOTION_TOKEN=
NOTION_DATABASE_ID=
SEC_USER_AGENT="wyrd.exe research your@email.com"
```

## 11. Build phases

Build one phase at a time. At the end of each phase: run tests, verify acceptance criteria, summarize, list anything unverified, and **stop for review.**

**Phase 0: Foundation**
- Monorepo scaffold, Makefile, `.env.example`, config files with starter values, prompts folder with placeholder prompts.
- SQLite schema + migrations + FTS5.
- Provider modules (Groq, Gemini, NVIDIA) and the router with fallback, retries, JSON validation, and usage logging.
- Source modules with a simple CLI for each (`python -m apps.api.sources.edgar search "Circuit City"`), printing JSON.
- *Acceptance:* `make setup` and `make dev` work; each provider has a passing "test connection"; each source CLI returns real data for a known company (Circuit City is a good test); router fallback demonstrated in a test by simulating a provider failure.

**Phase 1: UI shell**
- Next.js app with sidebar, theme, command palette, all pages with empty/loading states, SSE wiring, Settings page connected to config and key status.
- *Acceptance:* the app looks finished with mock data; Settings shows real key status; the PWA installs.

**Phase 2: Jobs, runs, and the dashboard**
- Job queue, run lifecycle, cancellation, log streaming, run detail view, quota meters from real `provider_usage` data.
- *Acceptance:* a dummy agent run streams logs live to Home and can be cancelled.

**Phase 3: @scout**
- News mode and evergreen gap-finder mode, dedup, scoring, Stories page fully working (table + board + detail drawer).
- *Acceptance:* a scout run returns scored, deduplicated stories with sources; gap finder stays within its YouTube unit budget.

**Phase 4: @outlier**
- Channel resolution, scanning, Shorts/long split, outlier scoring, Gemini analysis, Outliers page.
- *Acceptance:* scanning the three seed channels produces outlier records with analysis, using well under 1,000 YouTube units.

**Phase 5: Orchestrator + chat**
- MCP server, Claude Code headless integration, chat UI with streaming, plan cards, @mention fast path, session resume, memory search.
- *Acceptance:* "find me 10 fraud stories and check what's working on Company Man" yields one plan card with two steps; approving runs both; the orchestrator summarizes results; a new chat can recall them via memory.

**Phase 6: @researcher**
- Subagent definition, source tools via MCP, Gemini extraction, NVIDIA second opinion, dossier save + markdown export, Research page.
- *Acceptance:* a standard-depth dossier on Circuit City where every Key Numbers row has a source URL and excerpt, exported to `research/circuit-city/`.

**Phase 7: Notion sync**
- Push/pull as specified; Settings controls.
- *Acceptance:* stories appear in Notion; changing Status in Notion updates the app after sync.

## 12. Non-goals for v1

- No cloud hosting, no multi-user accounts, no authentication beyond binding to localhost.
- No scheduled runs (on-demand only).
- No script writing inside the engine (scripting happens in the owner's Claude Project "Script Room"; the engine only exports dossiers for it).
- No fact-check or graphics agents yet (reserved slots only).

## 13. v2 Roadmap

Planned after v1 (Phases 0–7). **Nothing here is built yet.** Each phase follows the same rules as v1: verify current docs, licenses and limits first, build one phase at a time, and stop for review. Facts below were checked on 2026-10-05; re-verify them at build time.

**Phase 8: @graphics**
- Reads `[GRAPHIC]` cues from finished scripts (exported from Script Room) and renders each as a **transparent video clip** for the edit, using Remotion templates.
- Templates: animated counters ("$1.4B"), bar/line charts, timelines, map pins, quote cards, logo reveals. Every number, date and quote must come from the story's dossier (Key Numbers, Timeline, sources), never from the script text alone.
- Output: transparent clips (ProRes 4444 / WebM with alpha), one per cue, named by cue order, saved under `research/<slug>/graphics/`. Renders run as normal agent jobs with plan approval.
- License: Remotion is free for individuals, for-profit companies with up to 3 employees, and non-profits; larger companies need a Company License (remotion-dev/remotion `LICENSE.md`). Confirm the current terms before building.

**Phase 9: phone access**
- Reach the app from the owner's phone over **Tailscale** (free Personal plan: up to 6 users, unlimited devices) with `tailscale serve`, which proxies a local port to HTTPS on the tailnet only (not public; Funnel is a separate, public feature). Servers stay bound to 127.0.0.1; Tailscale forwards to them. Serve requires HTTPS certificates to be enabled for the tailnet.
- The browser must reach the API through the same origin as the web app (see decisions), so one served port is enough.
- Mobile-friendly layout pass: sidebar becomes a bottom/drawer nav, Stories board scrolls horizontally, plan cards and run logs fit a phone, touch-friendly approve/cancel.
- Verify the current free plan and the `tailscale serve` syntax before building.

**Phase 10: analytics feedback loop**
- Connect the owner's YouTube channel with Google OAuth (read-only scopes) and pull each published video's views, average view duration, average view percentage, and retention curve (`audienceWatchRatio`) from the **YouTube Analytics API**.
- Thumbnail impressions and click-through rate are documented in the **YouTube Reporting API** (`video_thumbnail_impressions`, `video_thumbnail_impressions_ctr`, bulk daily reports). Check whether the Analytics API exposes them too before choosing.
- Link each video to its story, compare performance with the story's @scout scores, and **suggest** (never auto-apply) rubric weight changes in Settings, with the evidence (e.g. "twist correlates with retention; freshness doesn't").

**Later (unscheduled)**
- **@factcheck**: claim extraction from scripts and verification against dossier sources (see `fact-check-protocol.md`).
- **Scheduled runs**: local cron and/or GitHub Actions for recurring scouts and outlier scans (still plan-gated unless auto-approve is on).
