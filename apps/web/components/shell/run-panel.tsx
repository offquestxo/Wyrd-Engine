"use client"

import Link from "next/link"
import { PanelRightCloseIcon, TrashIcon } from "lucide-react"
import { useEffect, useRef } from "react"

import { AgentTag, RunStatusBadge } from "@/components/common/badges"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useEvents } from "@/hooks/use-events"
import { useRuns } from "@/hooks/use-live"
import { useNow } from "@/hooks/use-now"
import { clock, duration } from "@/lib/format"
import { cn } from "@/lib/utils"

/** Collapsible right panel: active runs + the live SSE event feed (run logs, system events). */
export function RunPanel({ onClose }: { onClose: () => void }) {
  const { events: all, status, clear } = useEvents()
  // Chat traffic has its own page; keep the feed to runs, plans and system events.
  const events = all.filter((e) => !e.type.startsWith("chat."))
  const { data } = useRuns("status=running,queued&limit=10")
  const runs = data ?? []
  const now = useNow()
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [events.length])

  return (
    <aside className="flex h-full w-80 shrink-0 flex-col border-l bg-sidebar" aria-label="Live runs">
      <div className="flex h-14 items-center justify-between border-b px-4">
        <span className="text-sm font-medium">Live</span>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close panel (⌘.)">
          <PanelRightCloseIcon />
        </Button>
      </div>

      <div className="border-b p-3">
        <p className="mb-2 px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          Active runs
        </p>
        {runs.length === 0 ? (
          <p className="px-1 text-xs text-muted-foreground">No agents running.</p>
        ) : (
          runs.map((run) => (
            <Link
              key={run.id}
              href={`/runs/${run.id}`}
              className="block rounded-md border p-2.5 transition-colors hover:bg-sidebar-accent"
            >
              <div className="flex items-center justify-between">
                <AgentTag agent={run.agent} />
                <RunStatusBadge status={run.status} />
              </div>
              <p className="mt-1.5 truncate text-xs text-foreground/80">{run.current_step}</p>
              <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-brand transition-all" style={{ width: `${(run.progress ?? 0) * 100}%` }} />
              </div>
              <p className="mt-1.5 font-mono text-[10px] text-muted-foreground">
                run #{run.id} · {run.started_at ? duration(run.started_at, null, now) : "queued"}
              </p>
            </Link>
          ))
        )}
      </div>

      <div className="flex items-center justify-between px-4 pt-3 pb-1">
        <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Event stream</p>
        <Button variant="ghost" size="icon-xs" onClick={clear} aria-label="Clear events">
          <TrashIcon />
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-1 px-4 pb-4 font-mono text-[11px] leading-5">
          {events.length === 0 && (
            <p className="text-muted-foreground">
              {status === "open"
                ? "Connected. Events from runs, provider tests, and config changes appear here."
                : "Waiting for the engine API on 127.0.0.1:8000…"}
            </p>
          )}
          {events.map((e) => (
            <div key={e.id} className="border-b border-border/50 pb-1.5">
              <div className="flex gap-2">
                <span className="text-muted-foreground/60">{clock(e.ts)}</span>
                <span className={cn(e.data.ok === false || e.type.endsWith("error") ? "text-destructive" : "text-brand")}>
                  {e.type}
                </span>
              </div>
              <p className="line-clamp-3 break-words text-foreground/80" title={describe(e.data)}>
                {describe(e.data)}
              </p>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
    </aside>
  )
}

function describe(data: Record<string, unknown>): string {
  const prefix = typeof data.run_id === "number" ? `#${data.run_id} ` : ""
  if (typeof data.message === "string") return prefix + data.message
  if (typeof data.status === "string" && prefix) return `${prefix}${data.status}${data.current_step ? ` · ${data.current_step}` : ""}`
  return Object.entries(data)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" ")
}
