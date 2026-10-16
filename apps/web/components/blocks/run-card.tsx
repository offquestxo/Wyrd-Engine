"use client"

import { CheckIcon, Loader2Icon, MinusIcon, XIcon } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { useNow } from "@/hooks/use-now"
import { api } from "@/lib/api"
import { clock, timeAgo } from "@/lib/format"
import type { RunRecord } from "@/lib/types"
import { cn } from "@/lib/utils"

/** mm:ss (or h:mm:ss) since `from`. */
function elapsed(fromIso: string, toIso: string | null, now: number): string {
  const end = toIso ? new Date(toIso).getTime() : now
  const total = Math.max(0, Math.round((end - new Date(fromIso).getTime()) / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, "0")
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${String(m).padStart(2, "0")}:${s}`
}

/** "topic=Bre-X depth=quick" → "Bre-X · quick" (values only, short). */
export function paramsSummary(params: Record<string, unknown> | null): string {
  if (!params) return ""
  return Object.values(params)
    .filter((v) => v !== null && v !== "" && typeof v !== "object")
    .map(String)
    .slice(0, 4)
    .join(" · ")
}

/**
 * A live agent run: agent (cyan while live), params, elapsed, progress (step segments when the
 * caller knows the steps, else one bar), the last 3 log lines, Open / Stop.
 * Finished runs collapse to one line.
 */
export function RunCard({ run, steps, className }: { run: RunRecord; steps?: string[]; className?: string }) {
  const now = useNow()
  const [stopping, setStopping] = useState(false)
  const live = run.status === "running" || run.status === "queued"

  const stop = async () => {
    setStopping(true)
    try {
      await api(`/api/runs/${run.id}/cancel`, { method: "POST" })
      toast.success(`Run #${run.id} stopped`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setStopping(false)
    }
  }

  if (!live) {
    const summary = run.error ?? (run.result?.summary as string | undefined) ?? run.current_step ?? paramsSummary(run.params)
    const Icon = run.status === "succeeded" ? CheckIcon : run.status === "failed" ? XIcon : MinusIcon
    return (
      <article className={cn("flex flex-wrap items-center gap-3 rounded-xl border bg-card px-[18px] py-4", className)}>
        <span
          className={cn(
            "flex size-[22px] shrink-0 items-center justify-center rounded-full",
            run.status === "succeeded" && "bg-success/15 text-success-text",
            run.status === "failed" && "bg-destructive/15 text-destructive-text",
            run.status === "cancelled" && "bg-muted text-subtle-foreground",
          )}
          aria-label={run.status}
        >
          <Icon className="size-3" strokeWidth={3} />
        </span>
        <span className="font-mono text-sm font-semibold">@{run.agent}</span>
        <span className={cn("min-w-0 flex-[1_1_220px] truncate text-sm", run.status === "failed" ? "text-destructive-text" : "text-muted-foreground")}>
          {summary}
        </span>
        {run.finished_at && <span className="num text-xs text-subtle-foreground">{timeAgo(run.finished_at, now)}</span>}
        <Button asChild size="sm" variant="secondary" className="h-9">
          <Link href={`/runs/${run.id}`}>Open run</Link>
        </Button>
      </article>
    )
  }

  const active = steps ? Math.max(0, steps.findIndex((s) => run.current_step?.toLowerCase().startsWith(s.toLowerCase()))) : -1
  const pct = run.progress != null ? Math.round(run.progress * 100) : null
  return (
    <article
      className={cn(
        "flex flex-col gap-3.5 rounded-xl border bg-card p-[18px]",
        run.status === "running" && "border-transparent glow-live",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <span className={cn("font-mono text-sm font-semibold", run.status === "running" ? "text-live-text" : "text-muted-foreground")}>
          @{run.agent}
        </span>
        <span className="min-w-0 truncate text-sm">{paramsSummary(run.params)}</span>
        <span className="num ml-auto text-xs text-subtle-foreground">
          {run.status === "queued" ? "queued" : run.started_at ? `${elapsed(run.started_at, null, now)} elapsed` : ""}
        </span>
      </div>

      {steps ? (
        <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
          {steps.map((s, i) => (
            <div key={s} className="flex min-w-0 flex-col gap-1.5">
              <div className="h-1 overflow-hidden rounded-full bg-muted">
                {i < active && <div className="h-full bg-live" />}
                {i === active && <div className="h-full bg-live shadow-[0_0_10px_var(--live)]" style={{ width: `${pct ?? 50}%` }} />}
              </div>
              <span className={cn("truncate text-xs", i === active ? "font-medium text-foreground" : i < active ? "text-muted-foreground" : "text-subtle-foreground")}>
                {s}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className={cn("h-full bg-live shadow-[0_0_10px_var(--live)]", pct == null && "w-1/3 animate-pulse")}
              style={pct != null ? { width: `${Math.max(pct, 2)}%` } : undefined}
            />
          </div>
          <span className="num max-w-[55%] truncate text-xs">{run.current_step ?? (run.status === "queued" ? "Waiting to start" : "Starting")}</span>
        </div>
      )}

      {run.log_tail && run.log_tail.length > 0 && (
        <div className="rounded-[10px] border border-white/5 bg-[#08090d] px-3 py-2.5 font-mono text-xs leading-[1.75] text-subtle-foreground">
          {run.log_tail.slice(-3).map((log, i, arr) => (
            <div
              key={log.id}
              className={cn(
                "truncate",
                i === arr.length - 1 && "text-foreground",
                log.level === "warn" && "text-warning-text",
                log.level === "error" && "text-destructive-text",
              )}
            >
              <span className="text-[#5b6072]">{clock(log.ts)}</span> {log.message}
              {i === arr.length - 1 && run.status === "running" && <span className="text-live motion-safe:animate-pulse">▍</span>}
            </div>
          ))}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button asChild size="sm" variant="outline" className="h-9">
          <Link href={`/runs/${run.id}`}>Open run</Link>
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-9 border-destructive/35 text-destructive-text hover:bg-destructive/10 hover:text-destructive-text"
          disabled={stopping}
          onClick={() => void stop()}
        >
          {stopping && <Loader2Icon className="animate-spin" />} Stop
        </Button>
      </div>
    </article>
  )
}
