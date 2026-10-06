// Sample data still used by the Research page until @researcher lands (Phase 6). Every
// other page uses the real API. The page shows a "Sample data" badge while it uses this file.
//
// Research integrity: the sample dossier uses only facts and URLs that were fetched live from
// EDGAR, Wikipedia, and Hacker News during Phase 0 testing; everything else is marked sample.

import type { Dossier } from "./types"

const NOW = Date.now()
const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString()

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
