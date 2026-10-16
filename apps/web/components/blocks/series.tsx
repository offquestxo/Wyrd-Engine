import { seriesStyle } from "@/lib/series"
import { cn } from "@/lib/utils"

/** Small square in the series colour (tables, filter chips, legends). */
export function SeriesDot({ series, className }: { series: string | null | undefined; className?: string }) {
  const s = seriesStyle(series)
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2.5 shrink-0 rounded-[3px]", className)}
      style={{ background: s.block }}
    />
  )
}

/** Series label tinted with its block colour. `filter` = the square-dot filter-chip look. */
export function SeriesChip({
  series,
  variant = "tint",
  className,
}: {
  series: string | null | undefined
  variant?: "tint" | "filter"
  className?: string
}) {
  const s = seriesStyle(series)
  if (variant === "filter") {
    return (
      <span className={cn("inline-flex items-center gap-2 text-[13px]", className)}>
        <SeriesDot series={series} />
        {s.label}
      </span>
    )
  }
  return (
    <span
      className={cn("inline-flex items-center rounded-full px-2.5 py-1 text-[12.5px] leading-none", className)}
      style={{
        background: `color-mix(in oklab, ${s.block} 16%, transparent)`,
        color: `color-mix(in oklab, ${s.block} 55%, white)`,
      }}
    >
      {s.label}
    </span>
  )
}
