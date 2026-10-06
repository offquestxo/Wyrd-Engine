// Sample data for the Phase 1 UI shell. Each page shows a "Sample data" badge while it
// uses this file; Phases 2–6 replace these with real API calls.
//
// Research integrity: sample hooks and scores are illustrative only. The sample dossier
// uses only facts and URLs that were fetched live from EDGAR, Wikipedia, and Hacker News
// during Phase 0 testing; everything else is marked as sample text.

import type {
  AgentRun,
  ChatThread,
  Dossier,
  OutlierVideo,
  Plan,
  UsageMeter,
} from "./types"

const NOW = Date.now()
const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString()

const log = (minutesAgo: number, message: string, level: "info" | "warn" | "error" = "info") => ({
  ts: ago(minutesAgo),
  level,
  message,
})

export const MOCK_RUNS: AgentRun[] = [
  {
    id: 42, agent: "researcher", params: { story_id: 1, depth: "standard" }, status: "running",
    started_at: ago(6), finished_at: null, current_step: "Extracting key numbers from 10-K (2008)",
    progress: 0.55, providers: ["claude", "nvidia", "gemini"],
    logs: [
      log(6, "Planned 5 research questions"),
      log(5.5, "EDGAR: found 10-K filings for 2006–2008"),
      log(4, "Wayback: 3 yearly snapshots of circuitcity.com"),
      log(3, "gemini unavailable (401); extract_from_document fell back to nvidia", "warn"),
      log(1, "Extracting key numbers from 10-K (2008)"),
    ],
  },
  {
    id: 41, agent: "scout", params: { mode: "news", topic: "fraud", limit: 25 }, status: "succeeded",
    started_at: ago(48), finished_at: ago(45), providers: ["gemini:gemma", "nvidia"],
    summary: "18 new stories (7 duplicates skipped)",
    logs: [log(48, "Pulled 112 items from 9 feeds"), log(46, "Deduped to 25"), log(45, "Scored 25 items")],
  },
  {
    id: 40, agent: "outlier", params: { channels: ["@companyman"], threshold: 3 }, status: "succeeded",
    started_at: ago(130), finished_at: ago(127), providers: ["youtube", "nvidia"],
    summary: "6 outliers flagged · 4 YouTube units",
    logs: [log(130, "Resolved 1 channel"), log(128, "Fetched 50 videos"), log(127, "6 videos ≥ 3.0×")],
  },
  {
    id: 39, agent: "scout", params: { mode: "evergreen", limit: 20 }, status: "failed",
    started_at: ago(300), finished_at: ago(299), providers: ["wikipedia", "youtube"],
    error: "YouTube search budget exhausted (100/100 calls today)",
    logs: [log(300, "Crawled 5 categories"), log(299, "YouTube search cap reached", "error")],
  },
]

export const MOCK_PLAN: Plan = {
  id: 7, chat_id: 1, status: "pending", created_at: ago(2),
  summary: "Find 10 fraud stories, then check what's working on Company Man",
  steps: [
    { order: 1, agent: "scout", params: { mode: "news", topic: "fraud", limit: 10, series: "Fraud Files" },
      providers: ["groq → gemma → nvidia"], uses_claude: false },
    { order: 2, agent: "outlier", params: { channels: ["@companyman"], videos_per_channel: 50, threshold: 3, format: "both" },
      providers: ["youtube", "gemini → nvidia"], youtube_units: 3, uses_claude: false },
  ],
}

export const MOCK_THREADS: ChatThread[] = [
  {
    id: 1, title: "Fraud stories + Company Man", updated_at: ago(2),
    messages: [
      { id: 1, role: "user", created_at: ago(3),
        content: "find me 10 fraud stories and check what's working on Company Man" },
      { id: 2, role: "assistant", created_at: ago(2),
        content: "I'll run @scout for recent fraud news, then @outlier on Company Man's last 50 uploads. Here's the plan:",
        plan: MOCK_PLAN },
    ],
  },
  {
    id: 2, title: "Circuit City research", updated_at: ago(50),
    messages: [
      { id: 3, role: "user", created_at: ago(55), content: "@researcher Circuit City, standard depth" },
      { id: 4, role: "agent", created_at: ago(50), content: "",
        result: { agent: "researcher", run_id: 42, headline: "Researcher is building the Circuit City dossier",
          items: ["5 research questions planned", "3 primary sources found so far"], href: "/runs/42" } },
    ],
  },
  {
    id: 3, title: "What's in Tech Graveyard?", updated_at: ago(60 * 26),
    messages: [
      { id: 5, role: "user", created_at: ago(60 * 26), content: "What stories do we have in Tech Graveyard?" },
      { id: 6, role: "assistant", created_at: ago(60 * 26),
        content: "Four: **Quibi** (Inbox), **MoviePass** (Scripting), **Pets.com** (Inbox, from an outlier), and **Vine** (Published)." },
      { id: 7, role: "agent", created_at: ago(60 * 25), content: "",
        result: { agent: "scout", run_id: 41, headline: "Scout found 18 stories",
          items: ["Sample story A — 8.4", "Sample story B — 8.1", "Sample story C — 7.9"], href: "/stories" } },
    ],
  },
]

const CC_DOSSIER = `# Circuit City — Research Dossier

> **Sample dossier.** Only the facts with sources below come from live Phase 0 fetches; every line marked *(sample)* is placeholder text until @researcher runs in Phase 6.

## Summary
Circuit City was an American consumer electronics retailer founded in 1949 by Samuel Wurtzel as the Wards Company [1]. *(sample)* The full summary is written by @researcher.

## The Twist
*(sample)* The single most surprising, sourced fact goes here.

## Timeline
- **1949** — Founded by Samuel Wurtzel as the Wards Company [1]
- **2008-04-28** — Files its Form 10-K for the fiscal year ended February 29, 2008 [2]
- **2009-06** — Files an 8-K with its April 2009 monthly operating report [3]
- *(sample)* Further dated events, each with a source

## Key People
- **Samuel Wurtzel** — founder [1]

## Key Numbers
| Figure | Meaning | Source | Excerpt |
|---|---|---|---|
| 1949 | Founding year | [1] | "founded in 1949 by Samuel Wurtzel" |
| *(sample)* | Revenue, store count, layoffs | — | — |

## Story Beats
1. **Rise** — *(sample)*
2. **Peak** — *(sample)*
3. **Cracks** — *(sample)*
4. **Fall** — *(sample)*
5. **Aftermath** — *(sample)*

## Hook Ideas
1. *(sample)* Five hooks, each tied to a sourced fact

## Best Angle for a Short / Best Angle for Long-form
*(sample)*

## Open Questions / Unverified
- *(sample)* Anything not confirmed by a source lands here, never in the sections above.
`

export const MOCK_DOSSIERS: Dossier[] = [
  {
    id: 2, story_id: 1, story_title: "Circuit City", slug: "circuit-city", version: 2, versions: [1, 2],
    markdown: CC_DOSSIER, flags: 1, created_at: ago(40),
    sources: [
      { n: 1, url: "https://en.wikipedia.org/wiki/Circuit_City", title: "Circuit City — Wikipedia", primary: false },
      { n: 2, url: "https://www.sec.gov/Archives/edgar/data/104599/000119312508093063/d10k.htm", title: "Form 10-K FY2008 — SEC EDGAR", primary: true },
      { n: 3, url: "https://www.sec.gov/Archives/edgar/data/104599/000010459909000027/ex99-1.htm", title: "8-K Ex. 99.1, April 2009 operating report — SEC EDGAR", primary: true },
      { n: 4, url: "http://www.inc.com/magazine/20090501/why-circuit-city-failed-and-why-bh-thrives.html", title: "Spolsky: Why Circuit City Failed (Inc., 2009)", primary: false },
    ],
  },
  {
    id: 5, story_id: 6, story_title: "MoviePass", slug: "moviepass", version: 1, versions: [1],
    markdown: "# MoviePass — Research Dossier\n\n> **Sample dossier.** Placeholder until @researcher runs.\n\n## Summary\n*(sample)*\n",
    flags: 0, created_at: ago(60 * 30), sources: [],
  },
]

export const MOCK_OUTLIERS: OutlierVideo[] = [
  ["Company Man", "Sample: The Decline of a Mall Giant…What Happened?", false, 4_200_000, 610_000, "Department store chain", "The Decline of X…What Happened?"],
  ["Company Man", "Sample: Why This Restaurant Chain Is Disappearing", false, 2_900_000, 610_000, "Casual dining chain", "Why X Is Disappearing"],
  ["Modern MBA", "Sample: The Genius Strategy Behind a Discount Grocer", false, 3_100_000, 520_000, "Discount grocer", "The Genius Strategy Behind X"],
  ["Magnates Media", "Sample: How One Man Built a Fake Empire", false, 5_600_000, 900_000, "Startup (fraud)", "How One Man Built X"],
  ["Magnates Media", "Sample: The $1 Product That Made Billions", true, 8_800_000, 1_200_000, "Consumer goods", "The $N Product That Made Billions"],
  ["Modern MBA", "Sample: The App Everyone Used Then Forgot", true, 2_400_000, 450_000, "Mobile app", "The X Everyone Used Then Forgot"],
].map(([channel, title, isShort, views, median, type, pattern], i) => ({
  id: i + 1,
  video_id: `sample${i + 1}`,
  channel: channel as string,
  title: title as string,
  is_short: isShort as boolean,
  views: views as number,
  channel_median: median as number,
  outlier_score: Math.round(((views as number) / (median as number)) * 10) / 10,
  published_at: ago(60 * 24 * (12 + i * 9)),
  analysis: {
    topic: "Sample topic",
    company_type: type as string,
    hook_pattern: pattern as string,
    why_it_worked: "Sample analysis: generated by @outlier in Phase 4.",
    wyrd_angle: "Sample angle: a wyrd.exe take on this topic.",
  },
}))

export const MOCK_USAGE: UsageMeter[] = [
  { provider: "groq", label: "Groq", unit: "requests", used: 0, limit: 1000, calls: 0, errors: 0, fallbacks: 0, note: "No key — Gemma covers scoring" },
  { provider: "gemini", label: "Gemini", unit: "requests", used: 3, limit: 500, calls: 3, errors: 3, fallbacks: 0, note: "Key rejected (401) — falling back to NVIDIA" },
  { provider: "nvidia", label: "NVIDIA", unit: "requests", used: 128, limit: null, calls: 128, errors: 1, fallbacks: 9, note: "~40 requests/min" },
  { provider: "youtube", label: "YouTube", unit: "units", used: 412, limit: 10000, calls: 38, errors: 0, fallbacks: 0, note: "Search: 12 / 100 calls" },
  { provider: "claude", label: "Claude", unit: "runs", used: 4, limit: 20, calls: 4, errors: 0, fallbacks: 0, note: "Local count vs. daily soft cap" },
]
