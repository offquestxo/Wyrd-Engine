import { Badge } from "@/components/ui/badge"
import type { RunStatus, StoryStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

const STORY_COLORS: Record<StoryStatus, string> = {
  Inbox: "bg-muted-foreground",
  Shortlisted: "bg-info",
  Researching: "bg-brand",
  Scripting: "bg-chart-2",
  "Fact-check": "bg-warning",
  Recording: "bg-chart-5",
  Editing: "bg-chart-4",
  Published: "bg-success",
  Archived: "bg-muted-foreground/40",
}

export function StoryStatusBadge({ status }: { status: StoryStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-foreground/80">
      <span className={cn("size-1.5 rounded-full", STORY_COLORS[status])} />
      {status}
    </span>
  )
}

const RUN_STYLES: Record<RunStatus, string> = {
  queued: "border-border text-muted-foreground",
  running: "border-brand/40 bg-brand-muted text-brand",
  succeeded: "border-success/30 text-success",
  failed: "border-destructive/40 text-destructive",
  cancelled: "border-border text-muted-foreground",
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge variant="outline" className={cn("gap-1.5 font-mono text-[10px] uppercase", RUN_STYLES[status])}>
      {status === "running" && <span className="size-1.5 animate-pulse rounded-full bg-brand" />}
      {status}
    </Badge>
  )
}

export function AgentTag({ agent }: { agent: string }) {
  return <span className="font-mono text-xs text-brand">@{agent}</span>
}

export function ScoreBar({ value, max = 10 }: { value: number; max?: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 w-16 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-brand" style={{ width: `${(value / max) * 100}%` }} />
      </div>
      <span className="w-7 font-mono text-xs tabular-nums text-muted-foreground">{value}</span>
    </div>
  )
}
