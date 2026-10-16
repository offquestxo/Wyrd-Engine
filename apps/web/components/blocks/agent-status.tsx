import { cn } from "@/lib/utils"

export type AgentState = "running" | "idle" | "failed"

const LABEL: Record<AgentState, string> = { running: "running", idle: "idle", failed: "failed" }

/** Dot + label: running (cyan, glowing), idle (hollow), failed (red). */
export function AgentStatus({
  state,
  label,
  className,
}: {
  state: AgentState
  /** Override the word next to the dot (e.g. "running · 2"). */
  label?: React.ReactNode
  className?: string
}) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-xs", className)}>
      <span
        aria-hidden
        className={cn(
          "size-2 shrink-0 rounded-full",
          state === "running" && "animate-pulse bg-live shadow-[0_0_8px_var(--live)] motion-reduce:shadow-none",
          state === "idle" && "border border-subtle-foreground",
          state === "failed" && "bg-destructive",
        )}
      />
      <span
        className={cn(
          state === "running" && "text-live-text",
          state === "idle" && "text-subtle-foreground",
          state === "failed" && "text-destructive-text",
        )}
      >
        {label ?? LABEL[state]}
      </span>
    </span>
  )
}
