import { CheckIcon } from "lucide-react"

import { seriesStyle } from "@/lib/series"
import { cn } from "@/lib/utils"

const FIGURE_SIZES = {
  sm: [32, 26, 20, 16],
  lg: [52, 42, 32, 24],
} as const

/** Shrink long figures/fallback names so they stay on the block. */
function figureSize(text: string, size: "sm" | "lg"): number {
  const [xl, l, m, s] = FIGURE_SIZES[size]
  const n = text.length
  return n <= 6 ? xl : n <= 9 ? l : n <= 14 ? m : s
}

/**
 * A 16:9 thumbnail idea in the story's series colour: a big figure plus a short uppercase caption.
 * Figures come from the source text (stories.hook_figure) and stay unverified until a dossier's
 * Key Numbers confirm them (`verified`, shown as ✓). Without a figure, the company name is the
 * big text; nothing is invented.
 */
export function ThumbnailBlock({
  series,
  figure,
  caption,
  fallback,
  verified = false,
  size = "sm",
  concept = size === "lg",
  className,
}: {
  series: string | null | undefined
  figure?: string | null
  caption?: string | null
  /** Company or story name, shown big when there's no figure. */
  fallback: string
  verified?: boolean
  size?: "sm" | "lg"
  /** Show the "THUMBNAIL CONCEPT" label (drawer). */
  concept?: boolean
  className?: string
}) {
  const s = seriesStyle(series)
  const big = figure?.trim() || fallback
  const hasFigure = Boolean(figure?.trim())
  const status = hasFigure ? (verified ? "figure confirmed by the dossier" : "unverified lead, not yet confirmed by a dossier") : "no figure yet"
  return (
    <div
      role="img"
      aria-label={`${s.label} thumbnail: ${big}${caption ? `, ${caption}` : ""} (${status})`}
      className={cn(
        "relative flex aspect-video w-full flex-col justify-between overflow-hidden",
        size === "lg" ? "rounded-[14px] px-[18px] py-4" : "rounded-[10px] px-3 py-2.5",
        className,
      )}
      style={{ background: s.block, color: s.ink }}
    >
      <div className="flex items-start justify-between gap-2">
        {concept ? <span className="font-mono text-[11px] font-semibold tracking-[1px]">THUMBNAIL CONCEPT</span> : <span />}
        {hasFigure && (
          <span
            title={verified ? "Figure confirmed by the dossier's Key Numbers" : "Unverified lead: not yet confirmed by a dossier"}
            className={cn(
              "flex shrink-0 items-center justify-center rounded-full font-mono font-semibold",
              size === "lg" ? "size-6 text-xs" : "size-[18px] text-[10px]",
            )}
            style={{ background: `color-mix(in oklab, ${s.ink} 14%, transparent)` }}
          >
            {verified ? <CheckIcon className={size === "lg" ? "size-3.5" : "size-3"} strokeWidth={3} /> : "?"}
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <span
          className={cn("font-display font-extrabold leading-[0.95] tabular-nums", !hasFigure && "line-clamp-2")}
          style={{ fontSize: figureSize(big, size), letterSpacing: size === "lg" ? "-2px" : "-1px" }}
        >
          {big}
        </span>
        {caption && (
          <span
            className={cn(
              "font-display font-extrabold uppercase",
              size === "lg" ? "line-clamp-2 text-sm" : "truncate text-[10.5px] tracking-[0.2px]",
            )}
          >
            {caption}
          </span>
        )}
      </div>
    </div>
  )
}
