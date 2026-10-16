import { cn } from "@/lib/utils"

/** 1,240 → "1,240"; 14,400 → "14.4k"; 1,000 → "1k". */
export function compact(n: number): string {
  if (n >= 10_000) {
    const k = n / 1000
    return `${Number.isInteger(k) ? k : k.toFixed(1)}k`
  }
  if (n >= 1000 && n % 1000 === 0) return `${n / 1000}k`
  return n.toLocaleString("en-US")
}

export function meterTone(ratio: number): "live" | "warning" | "destructive" {
  return ratio >= 0.9 ? "destructive" : ratio >= 0.7 ? "warning" : "live"
}

const FILL = { live: "bg-live", warning: "bg-warning", destructive: "bg-destructive" } as const
const HINT = { live: "text-subtle-foreground", warning: "text-warning-text", destructive: "text-destructive-text" } as const

/**
 * Used vs. limit. Cyan below 70 %, amber from 70 %, red from 90 %.
 * With no known limit it shows the count only (no fake bar).
 */
export function MeterBar({
  label,
  used,
  limit,
  unit,
  hint,
  className,
}: {
  label: React.ReactNode
  used: number
  limit: number | null | undefined
  unit?: string
  /** e.g. "router will prefer NVIDIA soon". Shown under the bar, coloured like it. */
  hint?: React.ReactNode
  className?: string
}) {
  const ratio = limit ? Math.min(1, used / limit) : 0
  const tone = limit ? meterTone(ratio) : "live"
  const pct = Math.round(ratio * 100)
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-baseline justify-between gap-3 text-[13.5px]">
        <span className="truncate">{label}</span>
        <span className="num shrink-0 text-muted-foreground">
          {compact(used)}
          {limit ? ` / ${compact(limit)}` : ""}
          {unit ? ` ${unit}` : ""}
        </span>
      </div>
      {limit ? (
        <div
          role="meter"
          aria-label={typeof label === "string" ? label : undefined}
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={used}
          aria-valuetext={`${pct}% used`}
          className="h-2 overflow-hidden rounded-full bg-muted"
        >
          <div className={cn("h-full rounded-full transition-[width]", FILL[tone])} style={{ width: `${Math.max(pct, used > 0 ? 1 : 0)}%` }} />
        </div>
      ) : (
        <div className="h-2 rounded-full border border-dashed border-border" title="No known limit" />
      )}
      {(hint || (limit && tone !== "live")) && (
        <span className={cn("text-xs", HINT[tone])}>
          {limit && tone !== "live" ? `${pct}% used` : null}
          {limit && tone !== "live" && hint ? " · " : null}
          {hint}
        </span>
      )}
    </div>
  )
}
