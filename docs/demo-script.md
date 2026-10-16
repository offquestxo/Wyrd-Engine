# wyrd.exe — showcase demo script (5–8 minutes)

Everything on screen is real engine data: real stories, dossiers, runs and quotas. Timings below were
measured on 2026-10-16 with this setup.

## Before you record (10–15 minutes ahead)

1. **Start the app** in a terminal at the repo root:
   ```bash
   make dev
   ```
   It prints the web address. That's http://127.0.0.1:3000, or the next free port if another app
   holds 3000. Open it in Chrome at about 1440px wide.
2. **Check the sidebar footer:** "Claude CLI · ready". If it says "not logged in", run `claude auth login` in a terminal, then click the card and **Re-check**.
3. **Check Gemini:** Settings › API keys › GEMINI_AUTH › **Test**. If it fails, re-run the `gcloud auth application-default login …` command from the README. The login expires weekly while the Google OAuth app is in Testing mode.
4. **Researcher is the slow step** (a quick run took ~10 min; standard depth takes longer). Pick one:
   - **(a) Use an existing dossier:** Bre-X v2 or Circuit City v2. Recommended.
   - **(b) Start one ~15 min before recording:** Stories › open a Shortlisted story (e.g. FTX) › **Research this** › **Approve & run**. On camera, show it on Home as a live card, then open the finished dossier.
5. **Optional:** close the right-hand live panel (⌘.) or collapse the sidebar (⌘\) if you want a wider picture. The sidebar's Agents list and Claude card stay visible either way.
6. **Leave Plan #14** ("Scout 5 recent-news Fraud Files story leads") pending. It's the plan card you'll approve on camera. If it's gone, create a fresh one in step 3 below.

---

## 1. Home: mission control (~45 s)

**Where:** Home (g h).

**Say / point at:**
- **Header:** date line, "Mission control", and the live summary ("N agents running · 1 plan waiting for you · N new stories since yesterday").
- **Approval strip:** Plan #14 is waiting. Point at the chips: agents, providers, YouTube units, "no Claude usage". *Don't approve yet.*
- **Four tiles:** Inbox (with its 7-day sparkline), Shortlisted, Dossiers ready, Outliers this week.
- **Live agents:** recent runs collapse to one line; a running agent becomes a glowing cyan card with a progress bar, its current step and the last log lines.
- **Fuel today:** a meter per provider, plus the Claude soft cap. Mistral shows "disabled". Meters turn amber at 70% and red at 90%.
- **Pipeline strip** and **Top picks from @scout** (each with Shortlist / Research this).
- **Sidebar:** the Agents list (idle / running / failed) and the Claude CLI card.

## 2. ⌘K command palette (~20 s)

**Do:** press **⌘K**. Type `circ` to show story search (Circuit City), then clear it and show "Start an agent". Press **Esc**.
**Say:** "Every page, every agent, every story is one keystroke away. g + a letter jumps between pages."

## 3. Chat with the orchestrator → plan → approve → live run → results (~2–2.5 min)

**Where:** Chat (g c) › **New chat** (the cream button).

**Type** (no @):
```
Find 3 new Fraud Files story ideas from recent news.
```
**What happens:**
- **~5 s:** the orchestrator (Claude) replies in plain text.
- **Plan card:** a "Waiting for you" card appears, with a big **01**, @scout, param chips (mode=news, limit=3, series=Fraud Files), providers, 0 YouTube units, "no Claude".

**Do:** click the card and press **⌘⏎**, or click **Approve & run**.
- The card switches to Running. The sidebar's @scout turns cyan. The thread's status line says "@scout running".
- Optional: open Home in a second tab to show the live run card.
- **The run takes ~2 minutes** (fetch → dedup → score → save). Talk over it, or cut.

**Result:** "✓ @scout found 3 stories. Top 3:" appears as colour-blocked thumbnail ideas. The colour is the series. The figure is a real number from the headline; "?" means no dossier has confirmed it yet. Click a thumbnail to open that story.

*Shortcut:* if you'd rather not wait, approve **Plan #14** from Home at the start of the demo; its results are ready by the time you reach Chat.

## 4. @scout fast path (~30 s, plus the run in the background)

**Where:** the chat composer. Click the **@scout** quick button, or type `@`.
**Type:**
```
@scout 3 news stories about airlines
```
**What happens:**
- Instantly: "fast path · no Claude" under your message, then a plan card. Groq parsed the request; Claude wasn't used.
- Approve it: another ~2 min run in the background. Mention it and move on.

## 5. Stories board + drawer (~60 s)

**Where:** Stories (g s). Board view.

**Point at:**
- Series chips with counts. Click **Childhood Brands** (Blockbuster, American Apparel, Borders…), then **All series**.
- Columns by status: Inbox, Shortlisted (FTX, British Post Office), Researching, Scripting (Bre-X, Circuit City).
- Cards are thumbnail ideas:
  - **Bre-X** shows "70,000,000 troy ounces" with a **✓**: confirmed by its dossier's Key Numbers.
  - **FTX** shows "$8 billion" with a **?**: from the source text, not yet confirmed.
- Drag a card between columns to change its status (e.g. a Childhood Brands story to Shortlisted).

**Do:** click **Bre-X** to open the drawer.
- Large thumbnail and its confirmation line, the score, and the hook (labelled "Unverified lead").
- Series / format / status chips.
- **Scores** as bars, gap score, sources.
- **Research again**, **Move to…**, **Open sources**, and dossier **v1 / v2**.

## 6. "Research this" → dossier with sources and verified claims (~60 s)

**Start it:** in a story's drawer (e.g. FTX), click **Research this** → a plan card (Claude, up to N turns, sources). **Approve & run**.
- The card on the board glows cyan with live progress, and Home shows the run.
- **A standard run takes 10+ minutes.** Don't wait on camera. Use the pre-run dossier (option a or b above).

**Show the result:** click **v2** in the Bre-X drawer, or go to Research (g r) › **Bre-X**.
- **Tiles:**
  - Claims verified **29/29**, "support check: Groq".
  - Sources (primary count).
  - **Unresolved flags 0**, out of 50 second-opinion flags.
  - Versions 2.
- **Scroll the dossier:**
  - Summary and The Twist.
  - Timeline: every row has a source link and a short exact quote.
  - Key Numbers.
  - Open Questions / Unverified: claims that couldn't be verified go here, not into the story.
- **Point out:** v1 had **16 unresolved** medium/high flags (see the list), and v2 resolved them by sourcing, attributing ("widely considered…") or moving them to Open Questions.
- **Copy for Script Room** copies the dossier; **Open exported file** opens `research/bre-x/dossier.md`.

## 7. Outliers with Gemini analysis (~45 s)

**Where:** Outliers (g o).
- **Tiles:** videos scanned (150), flagged outliers (12), biggest outlier (33.6×), YouTube units today.
- **Channel chips** (Company Man / MagnatesMedia / Modern MBA) and **Both / Long-form / Shorts**.
- Click a row. The side panel shows "N× channel median", views vs. median, and the **Gemini analysis**: why it worked, hook pattern, topic, wyrd.exe angle (labelled "Unverified lead").
- **Create story from this** turns an outlier into an Inbox story.
- **Optional:** **Run @outlier** → plan card → approve. A scan of 3 channels × 50 videos takes ~3 s and 6 YouTube units.

## 8. Settings: providers, quotas, auto-approve, Notion sync (~60 s)

**Where:** Settings (g ,).
- **Providers & quotas:**
  - **Today** meters per provider.
  - **Task routing:** primary → fallbacks. Mistral is struck through ("disabled"); OpenRouter is the long-context last resort for extraction and outliers.
  - The models and free-tier limits table.
- **API keys:** every key "set" (masked). Click **Test** on one to show a live connection check.
- **Agents:** an **auto-approve** toggle per agent (off by default: every run waits for your OK). Below it, the **Claude** card: CLI status, version, **Re-check**, and the daily soft cap.
- **Notion:** "Optional mirror of the Stories table", with **Sync now**.
  - **Before recording:** sync once, so the on-camera sync only has to push recent changes (a few seconds). A first sync of many new stories takes ~0.4 s per story.
  - Show the result toast ("N created · N updated · N pulled from Notion"), then the "wyrd.exe Stories" database in Notion. Only **Status** and **Notes** sync back from Notion.

---

## Slow steps at a glance

| Step | Time | Tip |
|---|---|---|
| Orchestrator reply | ~5 s | — |
| @scout news run (limit 3–5) | ~2 min | Approve Plan #14 early, or cut. |
| @scout evergreen (gap finder) | ~2.5 min | Uses ~20 YouTube searches (100/day limit). |
| @outlier scan (3 × 50 videos) | ~3 s, plus Gemini analysis of new outliers | — |
| @researcher quick | ~10 min | Start before recording, or show Bre-X / Circuit City. |
| @researcher standard (the "Research this" default) | 10–20 min | Start before recording. |
| Notion Sync now | seconds (≈0.4 s per changed story) | Sync once before recording. |

## If something looks off on camera

- **"Engine offline"** in the sidebar: the API stopped. Re-run `make dev`.
- **A provider meter is amber or red:** the router moves work to fallbacks on its own. Mention it as a feature.
- **A plan card is stuck on Running:** open the run (Home › Open run) to see its live log.
