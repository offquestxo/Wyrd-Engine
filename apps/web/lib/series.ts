// The one place series colours live (docs/design/HANDOFF.md, Part 2 rule 3):
// colour blocks mean series, nothing else, never status or buttons.
import { SERIES, type Series } from "@/lib/types"

export interface SeriesStyle {
  /** Display name ("No series" for stories without one). */
  label: string
  /** Block colour (CSS var), used for thumbnail blocks, dots and chip tints. */
  block: string
  /** Dark ink for text on the block. */
  ink: string
  /** Short key for CSS/data attributes. */
  key: string
}

const STYLES: Record<Series, SeriesStyle> = {
  "Fraud Files": { label: "Fraud Files", key: "fraud", block: "var(--series-fraud)", ink: "var(--series-fraud-ink)" },
  "Tech Graveyard": { label: "Tech Graveyard", key: "tech", block: "var(--series-tech)", ink: "var(--series-tech-ink)" },
  "Childhood Brands": {
    label: "Childhood Brands",
    key: "childhood",
    block: "var(--series-childhood)",
    ink: "var(--series-childhood-ink)",
  },
  Comebacks: { label: "Comebacks", key: "comebacks", block: "var(--series-comebacks)", ink: "var(--series-comebacks-ink)" },
  "Everyday Genius": { label: "Everyday Genius", key: "genius", block: "var(--series-genius)", ink: "var(--series-genius-ink)" },
  "Recent Collapses": {
    label: "Recent Collapses",
    key: "collapses",
    block: "var(--series-collapses)",
    ink: "var(--series-collapses-ink)",
  },
}

const NONE: SeriesStyle = { label: "No series", key: "none", block: "var(--series-none)", ink: "var(--series-none-ink)" }

export function seriesStyle(series: string | null | undefined): SeriesStyle {
  return series && series in STYLES ? STYLES[series as Series] : NONE
}

/** Every series in display order (for filter chips and legends). */
export const SERIES_STYLES: SeriesStyle[] = SERIES.map((s) => STYLES[s])
