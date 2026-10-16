"use client"

import { Loader2Icon, RefreshCwIcon } from "lucide-react"
import { useState } from "react"
import useSWR from "swr"

import { ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { fetcher } from "@/lib/api"
import type { ClaudeState, ClaudeStatus } from "@/lib/types"

export const CLAUDE_STATE_LABEL: Record<ClaudeState, string> = {
  ready: "ready",
  logged_out: "not logged in",
  unknown: "status unknown",
  not_installed: "not installed",
}

export const claudeStateClass = (state: ClaudeState) =>
  state === "ready" ? "border-success/40 text-success" : state === "unknown" ? "text-muted-foreground" : "border-warning/40 text-warning"

/** Claude Code CLI status with a Re-check button and, when not ready, what the CLI printed. */
export function ClaudeStatusPanel() {
  // /api/system/claude always runs a fresh check.
  const { data, error, isLoading, mutate } = useSWR<ClaudeStatus>("/api/system/claude", fetcher, { revalidateOnFocus: false })
  const [checking, setChecking] = useState(false)

  const recheck = async () => {
    setChecking(true)
    try {
      await mutate()
    } finally {
      setChecking(false)
    }
  }

  if (isLoading) return <LoadingState rows={2} />
  if (error) return <ErrorState error={error as Error} onRetry={() => void recheck()} />
  if (!data) return null
  return (
    <div className="space-y-2 rounded-lg border px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground">Claude Code CLI</span>
          <Badge variant="outline" className={claudeStateClass(data.state)}>
            {CLAUDE_STATE_LABEL[data.state]}
          </Badge>
          {data.version && <span className="font-mono text-xs text-muted-foreground">{data.version}</span>}
        </div>
        <Button size="sm" variant="outline" onClick={() => void recheck()} disabled={checking}>
          {checking ? <Loader2Icon className="animate-spin" /> : <RefreshCwIcon />} Re-check
        </Button>
      </div>
      {data.state !== "ready" && (
        <>
          <p className="text-xs text-muted-foreground">{data.detail}</p>
          {data.output && (
            <pre className="max-h-40 overflow-auto rounded-md bg-muted/40 px-3 py-2 font-mono text-[11px] whitespace-pre-wrap text-muted-foreground">
              <span className="text-foreground/70">$ claude auth status --json</span>
              {"\n"}
              {data.output}
            </pre>
          )}
        </>
      )}
    </div>
  )
}
