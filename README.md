# Wyrd-Engine

The story engine for **wyrd.exe**: it finds, reads, and researches true business stories, with a local dashboard of all agents and their tasks run by an orchestrator. Runs entirely on your computer.

`SPEC.md` is the source of truth for what gets built; `CLAUDE.md` holds the working rules.

**Status:** Phase 0 (foundation) is complete: config, database, the provider router, and the source modules. The web UI arrives in Phase 1.

## Requirements

- macOS or Linux
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for the project automatically)
- Node.js 20+ and [pnpm](https://pnpm.io/installation)
- [Claude Code](https://claude.com/claude-code) CLI, logged in (`claude auth login`). This is used by the orchestrator and @researcher from Phase 5.

## Setup

```bash
git clone https://github.com/offquestxo/Wyrd-Engine.git
cd Wyrd-Engine
make setup          # installs Python + JS deps, creates .env, creates data/wyrd.db
```

Then open `.env` and add your keys (see below). `.env` and `data/` are git-ignored, so never commit them.

```bash
make check-providers   # tests each API key (Groq, Gemini, NVIDIA, YouTube)
make check-models      # checks configured model IDs against each provider's live list
make dev               # API on http://127.0.0.1:8000, web on http://127.0.0.1:3000
make test              # lint + type check + offline tests (Python and web)
make test-live         # hits the real APIs with Circuit City as the test company
```

## API keys

All are free. Only `SEC_USER_AGENT` is needed for the keyless sources. Everything else degrades gracefully when a key is missing.

| `.env` variable | What it's for | Where to get it |
|---|---|---|
| `GROQ_API_KEY` | Fast scoring, @mention parsing | [console.groq.com/keys](https://console.groq.com/keys) → *Create API Key* |
| `GEMINI_API_KEY` | Long documents (10-Ks, court filings), outlier analysis, Gemma scoring | Must be a standard key starting with `AIza`. New AI Studio keys start with `AQ.` and are currently rejected by the Gemini API (a known Google issue). Instead, open [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials) for your AI Studio project → *Create credentials → API key*, and restrict it to the *Generative Language API*. Your free-tier limits are shown at [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) |
| `NVIDIA_API_KEY` | Dossier second opinions, embeddings | [build.nvidia.com](https://build.nvidia.com) → sign in → profile menu → *API Keys* → *Generate* (starts with `nvapi-`) |
| `YOUTUBE_API_KEY` | @outlier stats, gap-finder coverage checks | [Google Cloud Console](https://console.cloud.google.com/): create a project → enable [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) → *APIs & Services → Credentials → Create credentials → API key*. Restrict the key to the YouTube Data API |
| `COURTLISTENER_TOKEN` | Higher limits for lawsuits/bankruptcy dockets (optional; anonymous search works) | Create an account at [courtlistener.com](https://www.courtlistener.com/), then copy your token from your profile's API page (see [API help](https://www.courtlistener.com/help/api/rest/)) |
| `NOTION_TOKEN`, `NOTION_DATABASE_ID` | Optional Notion mirror (Phase 7) | [notion.so/profile/integrations](https://www.notion.so/profile/integrations) → *New integration* → copy the secret; share your stories database with the integration |
| `SEC_USER_AGENT` | Required by SEC EDGAR (no key) | Set to your name or app plus a contact email, e.g. `"wyrd.exe research you@example.com"` |

Model IDs and free-tier limits live in `config/providers.yaml`. Free tiers change often, so edit that file (or Settings, from Phase 1) when they do.

## Source CLIs

Every source prints JSON: `{"source", "command", "ok", "data" | "error"}`.

```bash
uv run python -m apps.api.sources.edgar search "Circuit City"
uv run python -m apps.api.sources.edgar filings 104599 --forms 10-K
uv run python -m apps.api.sources.edgar fulltext '"Circuit City" liquidation' --forms 8-K
uv run python -m apps.api.sources.edgar facts 764478          # XBRL (2009+ filers only)
uv run python -m apps.api.sources.wikipedia article "Circuit City"
uv run python -m apps.api.sources.wikipedia pageviews "Circuit City" --days 60
uv run python -m apps.api.sources.wayback snapshots circuitcity.com --from 2007 --to 2009
uv run python -m apps.api.sources.courtlistener search "Circuit City Stores"
uv run python -m apps.api.sources.loc_newspapers search "Circuit City"
uv run python -m apps.api.sources.internet_archive search '"Circuit City"' --mediatype texts
uv run python -m apps.api.sources.news_rss search "Circuit City"
uv run python -m apps.api.sources.hackernews search "Circuit City"
uv run python -m apps.api.sources.reddit_rss search "Circuit City" --subreddit business
uv run python -m apps.api.sources.gdelt search "Circuit City"
uv run python -m apps.api.sources.yahoo history BBY --period 5y
uv run python -m apps.api.sources.youtube channel @companyman
```

Run `--help` on any module for all commands.

## Layout

```
config/        providers, sources, channels, scoring (YAML)
prompts/       every LLM prompt (.md)
apps/api/      FastAPI backend: db/, providers/ (router), sources/, agents/
apps/web/      Next.js frontend
research/      exported dossiers (git-tracked)
data/          SQLite database (git-ignored)
docs/          decisions log
```
