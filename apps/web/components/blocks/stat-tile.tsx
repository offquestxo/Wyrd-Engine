import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export type Tone = "neutral" | "live" | "success" | "warning" | "destructive"

export const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-subtle-foreground",
  live: "text-live-text",
  success: "text-success-text",
  warning: "text-warning-text",
  destructive: "text-destructive-text",
}

/** Tiny trend line (no axes): shape only, the number next to it carries the value. */
export function Sparkline({ values, className }: { values: number[]; className?: string }) {
  if (values.length < 2) return null
  const w = 72
  const h = 26
  const max = Math.max(...values)
  const min = Math.min(...values)
  const span = max - min || 1
  const points = values
    .map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / span) * (h - 4)).toFixed(1)}`)
    .join(" ")
  return (
    <svg aria-hidden width={w} height={h} viewBox={`0 0 ${w} ${h}`} className={cn("shrink-0 text-live", className)}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

/** A KPI: label, big mono number, optional sparkline or aside, and a delta line. */
export function StatTile({
  label,
  value,
  sparkline,
  aside,
  delta,
  deltaTone = "neutral",
  loading = false,
  compact = false,
  className,
}: {
  label: string
  value: number | string | null | undefined
  sparkline?: number[]
  aside?: React.ReactNode
  delta?: React.ReactNode
  deltaTone?: Tone
  loading?: boolean
  /** Smaller number (28px) for tiles inside a page section rather than a KPI row. */
  compact?: boolean
  className?: string
}) {
  return (
    <div className={cn("flex flex-col gap-2.5 rounded-xl border bg-card", compact ? "p-4" : "p-[18px]", className)}>
      <span className="text-[13px] text-muted-foreground">{label}</span>
      <div className="flex items-end justify-between gap-2">
        {loading ? (
          <Skeleton className="h-9 w-16" />
        ) : (
          <span className={cn("num leading-none font-semibold tracking-[-1px]", compact ? "text-[28px]" : "text-[36px]")}>
            {value ?? "—"}
          </span>
        )}
        {aside ?? (sparkline && <Sparkline values={sparkline} />)}
      </div>
      {delta && <span className={cn("num text-[11.5px]", TONE_TEXT[deltaTone])}>{delta}</span>}
    </div>
  )
}
