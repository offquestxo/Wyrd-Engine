# Handoff: fix the Claude agent, then the UI redesign

**From:** owner + Claude (design session, 2026-10-16)
**For:** Claude Code working in this repo
**Order:** Part 1 first (it blocks the orchestrator and @researcher). Then Part 2, one stage at a time.
Follow CLAUDE.md as usual: verify, run `make test`, summarize, **stop for review** after each part/stage.

Mockups (reference markup, not runnable code; they need a design-tool runtime, so read them for layout,
spacing, colours and copy, do not import them):

| File | What it shows | Style |
|---|---|---|
| `docs/design/mockups/home.dc.html` | Home dashboard | A · data |
| `docs/design/mockups/outliers.dc.html` | Outliers page | A · data |
| `docs/design/mockups/chat.dc.html` | Chat with plan card, result thumbnails, composer | Creative (B blocks in A shell) |
| `docs/design/mockups/stories.dc.html` | Stories board + story drawer | Creative (B blocks in A shell) |
| `docs/design/mockups/reference-direction-b.dc.html` | The original B exploration, for mood only | reference |

All numbers, stories and video topics in the mockups are **sample data**. The real app must keep showing real data only.

---

## Part 1: the Claude agent isn't working

### Symptom
The owner reports the Claude-powered parts (orchestrator chat, @researcher) don't work.

### Evidence found so far (read-only look at `data/wyrd.db`)
- Last orchestrator attempt: chat #5, 2026-10-07 21:59, system message:
  *"The orchestrator is unavailable: Claude Code is installed but not logged in. Run `claude auth login`."*
- That text comes from `apps/api/system.py::check_claude_cli()`, which runs `claude auth status --json`
  and requires `loggedIn == true` **and** exit code 0.
- All earlier runs succeeded (last @researcher run #10 on 2026-10-06; last fast-path @outlier run #11 on 2026-10-07).
  So it broke between 2026-10-07 02:35 and 21:59. The @mention fast path (Groq) is unaffected.

### Likely causes (check in this order)
1. **Really logged out / token expired.** Run `claude auth status` in the owner's terminal. If logged out → ask the
   owner to run `claude auth login` (don't do the login for them). Then retest.
2. **The check is wrong, not the login.** The CLI may have auto-updated and changed `auth status` (flag removed,
   JSON key renamed, different exit code, or output on stderr). Check `claude --version` and `claude auth status --help`
   against current docs. If the format changed, make the check tolerant: parse what the current CLI actually prints,
   and if status can't be determined, **don't block**: try the real call and surface its error instead.
3. **Different environment under `make dev`.** The backend's spawned process may see a different `PATH`, `HOME`,
   or config dir than the owner's terminal (e.g. two `claude` installs, nvm vs Homebrew, `CLAUDE_CONFIG_DIR`).
   Log `shutil.which("claude")`, `--version` and HOME from inside the API process and compare with the terminal.
4. **macOS keychain access.** If credentials live in the keychain, a background process may be denied access.
   Check for keychain prompts/errors in the `claude` stderr captured by `orchestrator.py`.
5. **Headless flags changed.** Once auth is OK, run one orchestrator turn and one tiny @researcher run. Compare
   flags used in `agents/orchestrator.py` and `agents/researcher.py` (`-p`, output/stream format, `--resume`,
   allowed tools, MCP config, system prompt) with `claude --help` for the installed version.

### Also fix
- The "not logged in" banner/message should show the **actual** CLI output (trimmed, no secrets) so the next failure
  explains itself. Add a "Re-check" button on the Settings › Claude card that re-runs the check.
- Add a test that feeds `check_claude_cli()` the current CLI's real output format (and an unknown format → "unknown",
  not "logged out").

### Done when
- Settings › Claude shows ready with the installed version.
- A chat message (not @mention) gets an orchestrator reply and produces a plan card.
- A quick-depth @researcher run completes and saves a dossier.
- Root cause + fix written in `docs/decisions.md`. **Stop for review.**

---

## Part 2: UI redesign ("A shell, creative blocks")

### The idea in one line
Pages where the owner **reads numbers** (Home, Outliers, Research, Settings, run detail) use style **A**:
calm, dark, precise. Pages where the owner **hunts for ideas** (Chat, Stories) keep the same shell but add
**B-style colour blocks**: thumbnail ideas built from a story's striking number, colour-coded by series.

### Rules (apply everywhere)
1. **One shell.** Same dark background, sidebar, command palette, live run panel on every page.
2. **One brand accent: violet**, for primary actions, focus rings, the active nav item and "needs you" states.
   Keep `--brand` as the single token so the owner can still swap it.
3. **Colour blocks mean series, nothing else.** Never use series colours for status or buttons.
4. **Status colours:** cyan = running/live, green = done, amber = near limit/warning, red = failed/stop.
5. **Numbers are always Geist Mono with tabular figures.**
6. Keyboard-first stays: ⌘K, g+key nav, plus ⌘⏎ = approve the focused plan card.
7. Every page keeps loading, empty and error states. Respect `prefers-reduced-motion` for glows/pulses.
8. Touch targets ≥ 44px for primary actions; text contrast ≥ 4.5:1 (check muted greys on cards).

### Tokens (add to `apps/web/app/globals.css`; convert to oklch to match the file if you like)

Surfaces (A):
| Token | Hex | Use |
|---|---|---|
| `--background` | `#07080C` | app background (data pages) |
| `--background-creative` | `#0A0B10` | Chat/Stories background |
| `--sidebar` | `#0B0C12` | sidebar / rails |
| `--card` | `#0E1017` | cards on data pages |
| `--card-creative` | `#15171F` | cards on creative pages |
| `--muted` | `#1D2030` | meter tracks |
| `--border` | `rgba(255,255,255,0.07)` | 1px borders |
| `--foreground` | `#ECEEF5` | body text (data) |
| `--foreground-warm` | `#F3F1EC` | body text + "cream" surfaces (creative) |
| `--muted-foreground` | `#A3A8B8` / `#8C91A3` | secondary / tertiary text |

Accent and status:
| Token | Hex |
|---|---|
| `--brand` (violet, buttons) | `#7C3AED` (text on it: white) |
| `--brand-soft` (violet text/icons) | `#C4B5FD` |
| `--live` (cyan) | `#22D3EE`, text `#67E8F9` |
| `--success` | `#34D399`, text `#6EE7B7` |
| `--warning` | `#FBBF24`, text `#FCD34D` |
| `--destructive` | `#F87171`, text `#FCA5A5` |

Series colours (new; text on the block uses the dark ink colour):
| Series | Block | Ink |
|---|---|---|
| Fraud Files | `#FF5A36` | `#1A0803` |
| Tech Graveyard | `#3D7BFF` | `#050B1A` |
| Childhood Brands | `#FFD23F` | `#1A1403` |
| Comebacks | `#2EE6A8` | `#03140E` |
| Everyday Genius | `#B9A4FF` | `#120A2A` |
| Recent Collapses | `#F3F1EC` | `#0A0B10` |
| (no series) | `#2A2D3A` | `#F3F1EC` |

Put the series map in one place (e.g. `lib/series.ts`) and use it everywhere a series appears.

Glow (use sparingly, only on "live" or "needs you" elements):
`box-shadow: 0 0 0 1px <colour>/40%, 0 0 32px <colour>/16%`.
Background on data pages: a faint 40px grid (`rgba(255,255,255,0.025)` lines). Creative pages: plain.

### Type
- Keep **Geist** (body/UI) and **Geist Mono** (numbers, agent names, logs, kbd).
- Add **Bricolage Grotesque** (via `next/font/google`, weights 500/700/800) for **headings on creative pages and
  the numbers inside thumbnail blocks only**. Don't use it on data pages.
- Scale: page title 32–38px (-0.8 to -1.2 letter-spacing); section title 15px/600 (data) or 19–22px/800 (creative);
  body 14–15.5px; meta 12–13px. KPI numbers 36px/600.

### New shared components
| Component | Notes |
|---|---|
| `ThumbnailBlock` | 16:9, series colour, big figure + short uppercase caption. Sizes: `sm` (figure 30–32px, cards), `lg` (figure ~52px, drawer). Fallback when no figure: company name as the big text. |
| `SeriesChip` / `SeriesDot` | From the series map. |
| `StatTile` | Label, big mono number, optional sparkline, delta line. |
| `MeterBar` | Used/limit, colour shifts to amber at ≥ 70% and red at ≥ 90%, optional hint text ("router will prefer NVIDIA soon"). |
| `RunCard` | Agent name (mono, cyan when live), params summary, elapsed, step segments, 3-line log tail, Open/Stop. |
| `PlanCard` v2 | Replaces the current plan card look in both Home strip and Chat; numbered steps, param chips, providers, YouTube units, "uses Claude?" flag; Cancel / Edit / **Approve & run (⌘⏎)**. Edit stays an inline form. |
| `AgentStatus` | Dot + label: running (cyan glow), idle (hollow), failed (red). |

### Page by page

**Home** (`app/home-view.tsx`) · style A · see `home.dc.html`
- Header: date/time line in mono, "Mission control" title, one-line status summary built from real counts
  (running agents, pending plans, new stories since yesterday). Buttons: "Ask the orchestrator" (→ Chat), **New run** (N).
- Pending-approval strip using `PlanCard` compact (approve without leaving Home).
- 4 `StatTile`s: Inbox, Shortlisted, Dossiers ready, Outliers this week.
- Two columns: **Live agents** (`RunCard`s, finished ones collapse to one line) and **Fuel today** (`MeterBar` per
  provider + Claude soft cap, fallbacks count, error rate, reset time).
- Pipeline strip: count per status (horizontal, scrolls on small screens).
- Top picks from @scout: 3 cards with Shortlist / Research this.

**Sidebar** (`components/shell/sidebar.tsx`) · all pages
- Logo tile + `wyrd.exe` + "STORY ENGINE · v1".
- Nav with counts (Stories, Research) and an "N new" pill on Outliers.
- New **Agents** section: one row per agent from the registry with `AgentStatus`; clicking opens a run form.
- Footer card: Claude CLI status + Claude runs meter. (This is also where Part 1's status shows.)
- Chat/Stories/Outliers mockups show a collapsed 64px icon rail; support collapsing the sidebar (remember it).

**Chat** (`app/chat/chat-view.tsx`, `components/chat/*`) · creative · see `chat.dc.html`
- Thread list: each thread gets a small series tile (or an icon for outlier/research threads) and a status line
  ("Plan waiting", "Dossier v2 · 18m").
- User bubble: cream (`#F3F1EC`) with dark text. Assistant text: plain, warm grey.
- `PlanCard` v2 with big "01 / 02" step numbers in Bricolage.
- Result cards: "✓ @scout found N stories. Top 4:" + a row of `ThumbnailBlock sm` linking to the stories.
- Composer: rounded card, quick @scout/@outlier/@researcher buttons, Send. Keep the existing @-autocomplete.

**Stories** (`app/stories/stories-view.tsx`, `components/stories/*`) · creative · see `stories.dc.html`
- Bricolage page title, Table/Board toggle (keep table as is but add `SeriesDot`), "Find stories" primary.
- Series filter chips with colour squares.
- Board columns by status; cards = `ThumbnailBlock sm` + name + mono score + series · format;
  Researching cards show live progress from the run. Keep drag-and-drop.
- Drawer: `ThumbnailBlock lg`, title + score, hook line, chips, **score bars in A style** (data inside a creative
  page), gap score, sources count (primary marked), Research this / Move to… / Open sources.

**Outliers** (`app/outliers/outliers-view.tsx`) · style A · see `outliers.dc.html`
- Summary tiles (scanned, flagged, biggest, YouTube units), channel chips, Long/Shorts toggle.
- Table with an outlier bar per row; selected row opens a side panel with Gemini analysis and
  "Create story from this".

**Research, Settings, run detail** · style A. Apply the tokens, `StatTile`/`MeterBar`, and the new card styles;
no layout redesign needed now.

### Data needed for thumbnails (important: research integrity)
Stories don't have a "figure" field yet. Add two optional fields to `stories`: `hook_figure` (e.g. "3,400") and
`hook_caption` (≤ 5 words). Have @scout's scoring step propose them **only from the source text it was given**,
and mark them unverified until a dossier's Key Numbers confirms the figure (then show a small ✓ on the block).
Never invent a figure. If missing, `ThumbnailBlock` falls back to the company name. Prompt changes go in
`prompts/scout_scoring.md`; new fields go through Pydantic validation like the rest.

### Suggested stages (stop for review after each)
1. Tokens, fonts, series map, shared components (with a simple dev-only preview page).
2. Shell (sidebar + agents section + Claude status) and Home.
3. Chat.
4. Stories (incl. the `hook_figure` / `hook_caption` fields and migration).
5. Outliers, then the token pass on Research/Settings/run detail.

### Done when
- Pages match the mockups' structure and feel using **real data**; no sample data left.
- `make test` passes (types, lint, pytest incl. migration).
- Works at 1440px and phone width (sidebar stacks/collapses, tables scroll in their box).
- PWA still installs; SSE live updates still work on Home, Chat and Stories.
- Decisions noted in `docs/decisions.md`.
