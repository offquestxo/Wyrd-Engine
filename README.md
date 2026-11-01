# Wyrd Engine

I run a faceless YouTube channel called **wyrd.exe** that tells true business stories (collapses, frauds, comebacks) like thrillers. The slowest part of making a video was never the editing. It was finding a good story and then reading enough 10-Ks, court filings and old news to tell it accurately.

So I built a research assistant for myself. Wyrd Engine runs on my laptop and does three jobs:

- **@scout** finds story ideas in news feeds and Wikipedia, and scores them.
- **@outlier** looks at competitor channels and flags the videos that did far better than usual, so I can see which topics work.
- **@researcher** writes a sourced research dossier on a story. Every date and number links to a source with a short exact quote.

I talk to it through a chat page. An orchestrator (Claude, through the Claude Code CLI) works out which agents to run and proposes a plan. Nothing runs until I approve it.

## How it's built

- **Backend:** Python, FastAPI, SQLite (with full-text search), and a small job queue that runs inside the API process. Live logs reach the browser over server-sent events.
- **Frontend:** Next.js, TypeScript, Tailwind and shadcn/ui. It can be installed as a desktop app from Chrome.
- **Models:** Claude is the planner and does the research writing. Everything high-volume goes to free tiers: Groq, Gemini, NVIDIA and OpenRouter.

The part I'm proudest of is the **provider router** (`apps/api/providers/router.py`). Agents never call a model directly. They ask for a task, like "score these headlines", and the router:

1. picks providers in the order set in `config/providers.yaml`, skipping any with no key or a recently rejected key, and moving any with less than 20% of their free quota left to the back of the line;
2. retries rate limits and server errors with exponential backoff (and honors `Retry-After`);
3. falls back to the next provider when one keeps failing;
4. validates every response against a Pydantic schema, gives the model one chance to repair invalid JSON, and treats a second failure like an outage;
5. logs every call (tokens, latency, success) so the dashboard can show how much of each free tier I've used today.

The reasons behind most design choices are in [`docs/decisions.md`](docs/decisions.md). [`SPEC.md`](SPEC.md) is the full spec I built against.

## Running it

You'll need macOS or Linux, [uv](https://docs.astral.sh/uv/), Node.js 20+ with [pnpm](https://pnpm.io/installation), and the [Claude Code](https://claude.com/claude-code) CLI logged in (`claude auth login`).

```bash
git clone https://github.com/offquestxo/Wyrd-Engine.git
cd Wyrd-Engine
make setup     # installs dependencies, creates .env and the database
```

Add your keys to `.env` (see below), then:

```bash
make check-providers   # tests each API key
make dev               # API on 127.0.0.1:8000, web app on 127.0.0.1:3000
make test              # lint, type checks and the offline test suite
make test-live         # tests against the real APIs, using Circuit City
```

If port 3000 is taken, `make dev` picks the next free one and prints it. `make dev WEB_PORT=3005` forces a port. Everything binds to 127.0.0.1 only.

## API keys

All of these have free tiers, and every one is optional. The app works around whichever keys are missing. `.env` is git-ignored.

| Variable | Used for | Get it at |
|---|---|---|
| `GROQ_API_KEY` | Fast scoring and parsing | [console.groq.com/keys](https://console.groq.com/keys) |
| `GEMINI_AUTH` / `GEMINI_API_KEY` | Reading long documents, outlier analysis | See [Gemini](#gemini) below |
| `NVIDIA_API_KEY` | Second-opinion checks, embeddings | [build.nvidia.com](https://build.nvidia.com) → API Keys |
| `OPENROUTER_API_KEY` | Last-resort fallback | [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) |
| `MISTRAL_API_KEY` | Wired in, switched off in config | [console.mistral.ai](https://console.mistral.ai/api-keys) |
| `YOUTUBE_API_KEY` | Channel and video stats | Google Cloud Console → enable YouTube Data API v3 → create an API key |
| `COURTLISTENER_TOKEN` | Higher limits on court records | [courtlistener.com](https://www.courtlistener.com/help/api/rest/) |
| `NOTION_TOKEN`, `NOTION_DATABASE_ID` | Mirror stories to Notion | [notion.so/profile/integrations](https://www.notion.so/profile/integrations) |
| `SEC_USER_AGENT` | Required by SEC EDGAR | Your name or app plus an email, e.g. `"wyrd.exe research you@example.com"` |

Model IDs and free-tier limits live in `config/providers.yaml`, because they change often. You can edit them from the Settings page too.

### Gemini

When I set this up (October 2026), new AI Studio keys in the `AQ.` format were rejected by the Gemini API, so the engine can sign in with your Google account instead. The short version:

1. In your Google Cloud project, enable the Generative Language API.
2. Set up the OAuth consent screen (External, add yourself as a test user) and create a **Desktop** OAuth client. Save its JSON as `~/.config/wyrd/client_secret.json`, outside the repo.
3. Give your account the **Service Usage Consumer** role on the project.
4. Log in:

   ```bash
   gcloud auth application-default login \
     --client-id-file="$HOME/.config/wyrd/client_secret.json" \
     --scopes="https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/generative-language.retriever"
   gcloud auth application-default set-quota-project YOUR_PROJECT_ID
   ```

5. Put `GEMINI_AUTH=oauth` in `.env` and click **Reload .env** in Settings.

While the OAuth app is in Testing mode, Google expires the login about once a week. Settings will tell you when to run step 4 again. A standard `AIza…` key also works if you have one.

## Using the app

Open the address `make dev` prints.

- **Home** shows running agents, pending plans, and today's usage for each provider.
- **Chat** is where you talk to the orchestrator. Start a message with `@scout` or `@outlier` to skip Claude: a fast model turns it straight into a plan card.
- **Stories** is a table or board of every story idea, with scores and sources.
- **Research** shows the dossiers. Any claim whose quote can't be found in its cited source is moved to "Open Questions" instead of being kept.
- **Outliers** lists competitor videos that beat their channel's median by 3× or more.
- **Settings** has key status, provider routing, per-agent auto-approve (off by default) and the Notion sync.

`⌘K` / `Ctrl+K` opens the command palette. `g` followed by `h`, `c`, `s`, `r`, `o` or `,` jumps between pages.

## Data sources

Each source has a small CLI that prints JSON, which made them easy to test on their own:

```bash
uv run python -m apps.api.sources.edgar search "Circuit City"
uv run python -m apps.api.sources.wikipedia article "Circuit City"
uv run python -m apps.api.sources.wayback snapshots circuitcity.com --from 2007 --to 2009
uv run python -m apps.api.sources.courtlistener search "Circuit City Stores"
uv run python -m apps.api.sources.youtube channel @companyman114
```

There are also modules for Library of Congress newspapers, the Internet Archive, Google News RSS, Hacker News, Reddit RSS, GDELT and Yahoo Finance. Run any of them with `--help`.

## Layout

```
apps/api/      FastAPI backend: agents, provider router, sources, database
apps/web/      Next.js frontend
config/        providers, sources, channels and scoring (YAML)
prompts/       every LLM prompt, as markdown
research/      exported dossiers (Circuit City and Bre-X are included)
tests/         pytest suite
docs/          decision log and demo notes
```
