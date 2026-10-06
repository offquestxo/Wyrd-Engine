"use client"

import { Loader2Icon, SquareIcon } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import { toast } from "sonner"

import { AgentTag, RunStatusBadge } from "@/components/common/badges"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useNow } from "@/hooks/use-now"
import { api } from "@/lib/api"
import { clock, duration, timeAgo } from "@/lib/format"
import type { RunRecord } from "@/lib/types"
import { cn } from "@/lib/utils"

export function RunRow({ run }: { run: RunRecord }) {
  const now = useNow()
  const [stopping, setStopping] = useState(false)
  const active = run.status === "running" || run.status === "queued"
  const cancel = async (e: React.MouseEvent) => {
    e.preventDefault() // the row is a link to the run
    e.stopPropagation()
    setStopping(true)
    try {
      await api(`/api/runs/${run.id}/cancel`, { method: "POST" })
      toast.success(`Run #${run.id} cancelled`)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setStopping(false)
    }
  }
  const headline =
    run.status === "running" || run.status === "queued"
      ? run.current_step
      : (run.error ?? (run.result?.summary as string | undefined) ?? run.current_step)
  return (
    <Link
      href={`/runs/${run.id}`}
      className="grid grid-cols-[110px_1fr_auto] items-start gap-4 border-b px-4 py-3 transition-colors last:border-b-0 hover:bg-muted/40"
    >
      <div className="flex flex-col items-start gap-1.5">
        <AgentTag agent={run.agent} />
        <RunStatusBadge status={run.status} />
      </div>
      <div className="min-w-0">
        <p className={cn("truncate text-sm", run.status === "failed" && "text-destructive")}>{headline ?? "—"}</p>
        {run.status === "running" && run.progress !== null && (
          <div className="mt-1.5 h-1 w-48 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-brand transition-all" style={{ width: `${run.progress * 100}%` }} />
          </div>
        )}
        <div className="mt-1.5 space-y-0.5 font-mono text-[11px] text-muted-foreground">
          {(run.log_tail ?? []).slice(-2).map((log) => (
            <p
              key={log.id}
              className={cn("truncate", log.level === "error" && "text-destructive", log.level === "warn" && "text-warning")}
            >
              <span className="text-muted-foreground/50">{clock(log.ts)}</span> {log.message}
            </p>
          ))}
        </div>
      </div>
      <div className="flex flex-col items-end text-right font-mono text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          {active && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon-xs"
                  variant="ghost"
                  onClick={(e) => void cancel(e)}
                  disabled={stopping}
                  aria-label={`Cancel run ${run.id}`}
                  className="text-muted-foreground hover:text-destructive"
                >
                  {stopping ? <Loader2Icon className="animate-spin" /> : <SquareIcon />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>Cancel run</TooltipContent>
            </Tooltip>
          )}
          <p>#{run.id}</p>
        </div>
        <p className="mt-1.5">
          {run.started_at
            ? run.status === "running"
              ? duration(run.started_at, null, now)
              : timeAgo(run.finished_at ?? run.started_at, now)
            : "queued"}
        </p>
      </div>
    </Link>
  )
}
