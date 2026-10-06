# Wyrd-Engine

The story engine for **wyrd.exe**: it finds, reads, and researches true business stories, with a local dashboard of all agents and their tasks run by an orchestrator. Runs entirely on your computer.

`SPEC.md` is the source of truth for what gets built; `CLAUDE.md` holds the working rules.

**Status:** Phases 0–3 are complete: foundation, UI shell, the job system (plans → approved runs with live logs, cancellation, real quota meters), and **@scout** (news + evergreen gap finder, dedup, scoring) with a fully working Stories page. Chat, Research, and Outliers show sample data (marked **SAMPLE DATA**) until Phases 4–6. Start a scout run with **Run @scout** on the Stories page or ⌘K.

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
| `GEMINI_AUTH` / `GEMINI_API_KEY` | Long documents (10-Ks, court filings), outlier analysis, Gemma scoring | Use OAuth: set `GEMINI_AUTH=oauth` after the steps in [Gemini via OAuth](#gemini-via-oauth-recommended). New AI Studio API keys (`AQ.` format) are rejected by the Gemini API; a standard `AIza` key also works if you have one. Your free-tier limits are at [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) |
| `MISTRAL_API_KEY` | Scoring, @mention parsing, long documents, outlier analysis (primary while Groq/Gemini are unavailable) | [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys) → *Create new key* (free "Experiment" plan; see your limits at [admin.mistral.ai/plateforme/limits](https://admin.mistral.ai/plateforme/limits)) |
| `OPENROUTER_API_KEY` | Last-resort free-model fallback for scoring and parsing | [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) → *Create key*. Free models allow 50 requests/day (1,000/day after buying $10 of credits) |
| `NVIDIA_API_KEY` | Dossier second opinions, embeddings | [build.nvidia.com](https://build.nvidia.com) → sign in → profile menu → *API Keys* → *Generate* (starts with `nvapi-`) |
| `YOUTUBE_API_KEY` | @outlier stats, gap-finder coverage checks | [Google Cloud Console](https://console.cloud.google.com/): create a project → enable [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) → *APIs & Services → Credentials → Create credentials → API key*. Restrict the key to the YouTube Data API |
| `COURTLISTENER_TOKEN` | Higher limits for lawsuits/bankruptcy dockets (optional; anonymous search works) | Create an account at [courtlistener.com](https://www.courtlistener.com/), then copy your token from your profile's API page (see [API help](https://www.courtlistener.com/help/api/rest/)) |
| `NOTION_TOKEN`, `NOTION_DATABASE_ID` | Optional Notion mirror (Phase 7) | [notion.so/profile/integrations](https://www.notion.so/profile/integrations) → *New integration* → copy the secret; share your stories database with the integration |
| `SEC_USER_AGENT` | Required by SEC EDGAR (no key) | Set to your name or app plus a contact email, e.g. `"wyrd.exe research you@example.com"` |

Model IDs and free-tier limits live in `config/providers.yaml`. Free tiers change often, so edit that file (or Settings, from Phase 1) when they do.

## Using the app

Open http://127.0.0.1:3000 after `make dev`. In Chrome or Edge, use the install icon in the address bar to install it as a desktop app.

| Shortcut | Action |
|---|---|
| `⌘K` / `Ctrl+K` | Command palette: jump to a page, start an agent, find a story |
| `g` then `h` `c` `s` `r` `o` `,` | Go to Home, Chat, Stories, Research, Outliers, Settings |
| `⌘.` / `Ctrl+.` | Toggle the live panel (active runs + event stream) |
| `⌘S` in a config editor | Save (validated before writing) |

**Settings** uses real data: key status and "Test connection", provider routes and limits, per-agent auto-approve (off by default), and editors for every file in `config/`. After editing `.env`, click **Reload .env** instead of restarting.

To preview a page's loading, empty, or error state, add `?state=loading`, `?state=empty`, or `?state=error` to its URL (sample-data pages only).

## Gemini via OAuth (recommended)

New Gemini API keys (`AQ.` format) are rejected by the Gemini API, so this engine signs in to Gemini with your Google account instead, using gcloud *Application Default Credentials* (ADC). These are the steps that worked (2026-10-05), adapted from [Google's OAuth quickstart](https://ai.google.dev/gemini-api/docs/oauth). Do them in the Google Cloud project behind your AI Studio account (often named `gen-lang-client-…`).

1. **Enable the API:** [Generative Language API](https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com) → *Enable*.
2. **Consent screen:** *Google Auth platform → Branding*: fill in the app name and your email. *Audience*: user type **External**, then under **Test users** add your own Google account. Without this, the browser login fails with `access_denied`.
3. **Desktop OAuth client:** *Google Auth platform → Clients → Create client → Desktop app*. Download the JSON and save it as `~/.config/wyrd/client_secret.json` (outside the repo; never commit it).
4. **Let your account use the project's quota:** *IAM & Admin → IAM → Grant access* → your account → role **Service Usage Consumer** (`roles/serviceusage.serviceUsageConsumer`). This provides the `serviceusage.services.use` permission.
5. **Install gcloud and log in** (a browser opens; the "Google hasn't verified this app" warning is expected for your own test app → *Continue*):

```bash
brew install --cask gcloud-cli
```

```bash
gcloud auth application-default login --client-id-file="$HOME/.config/wyrd/client_secret.json" --scopes="https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/generative-language.retriever"
```

6. **Set the quota project.** If gcloud asks to enable the **Cloud Resource Manager API**, say yes, or enable it in the console:

```bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

7. **Point the engine at OAuth:** in `.env`, add `GEMINI_AUTH=oauth` and comment out `GEMINI_API_KEY` (`# GEMINI_API_KEY=...`). Then click **Reload .env** in Settings (or restart `make dev`).
8. **Check it:** `make check-providers` should show Gemini as `connected via OAuth` with auth `oauth (ADC)`, and `make check-models` should list every configured Gemini model.

The engine reads `~/.config/gcloud/application_default_credentials.json` directly with Google's `google-auth` library, so gcloud doesn't need to be on the app's PATH. Access tokens refresh automatically, and the quota project from that file is sent as the `x-goog-user-project` header. While your OAuth app is in **Testing** mode, Google expires the login about once a week. When that happens, Settings and the affected run logs tell you to rerun the step 5 login command; then click **Reload .env**.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Browser login ends with `Error 403: access_denied` | Your account isn't a test user of the Testing-mode app | Step 2: *Audience → Test users → Add users* with the account you log in with |
| `PERMISSION_DENIED … serviceusage.services.use` (from `set-quota-project` or Gemini calls) | Your account can't bill usage to the quota project | Step 4: grant **Service Usage Consumer** on that project, wait a minute, retry |
| `set-quota-project` says the Cloud Resource Manager API is disabled | It's needed to look up the project | Enable [Cloud Resource Manager API](https://console.cloud.google.com/apis/library/cloudresourcemanager.googleapis.com), rerun step 6 |
| `default credentials were not found` / Settings says "no Application Default Credentials" | The step 5 login never completed (or ran under another user or `CLOUDSDK_CONFIG`) | Rerun step 5; check that `gcloud auth application-default print-access-token` prints a token |
| `make check-providers` shows Gemini with `auth: api_key` and an `AQ.` key error | `.env` has no `GEMINI_AUTH=oauth` line, so the engine used the API key | Add `GEMINI_AUTH=oauth` to `.env`, then **Reload .env** |
| "Google OAuth credentials expired or were revoked" | Testing-mode logins expire about weekly | Rerun step 5, then **Reload .env** |

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
