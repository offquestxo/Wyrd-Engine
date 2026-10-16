"use client"

import { RefreshCwIcon } from "lucide-react"
import useSWR from "swr"

import { ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useEvents } from "@/hooks/use-events"
import { API_BASE, fetcher } from "@/lib/api"
import { CLAUDE_STATE_LABEL, claudeStateClass } from "@/components/settings/claude-status"
import type { ClaudeStatus } from "@/lib/types"

export function SystemCard() {
  const claude = useSWR<ClaudeStatus>("/api/system/claude", fetcher, { revalidateOnFocus: false })
  const { status } = useEvents()

  return (
    <div className="divide-y rounded-lg border text-sm">
      <Row label="Claude Code CLI">
        {claude.isLoading ? (
          <LoadingState rows={1} className="w-64" />
        ) : claude.error ? (
          <ErrorState error={claude.error as Error} onRetry={() => claude.mutate()} className="py-4" />
        ) : (
          claude.data && (
            <div className="flex items-center gap-3">
              <Badge variant="outline" className={claudeStateClass(claude.data.state)}>
                {CLAUDE_STATE_LABEL[claude.data.state]}
              </Badge>
              <span className="font-mono text-xs text-muted-foreground">{claude.data.version ?? ""}</span>
              <Button size="icon-xs" variant="ghost" onClick={() => claude.mutate()} aria-label="Re-check Claude CLI">
                <RefreshCwIcon />
              </Button>
            </div>
          )
        )}
      </Row>
      {claude.data && claude.data.state !== "ready" && (
        <p className="px-4 py-2 text-xs text-muted-foreground">
          {claude.data.detail}
          {claude.data.output && <span className="mt-1 block font-mono text-[11px]">CLI said: {claude.data.output.replace(/\s+/g, " ")}</span>}
        </p>
      )}
      <Row label="Engine API"><span className="font-mono text-xs">{API_BASE || "same origin /api → 127.0.0.1:8000"}</span></Row>
      <Row label="Live events (SSE)">
        <Badge variant="outline" className={status === "open" ? "border-success/40 text-success" : "border-warning/40 text-warning"}>
          {status}
        </Badge>
      </Row>
      <Row label="Install as app">
        <span className="text-xs text-muted-foreground">Chrome/Edge: address bar → Install icon, or ⋮ → Cast, save, and share → Install page as app.</span>
      </Row>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3">
      <span className="text-muted-foreground">{label}</span>
      {children}
    </div>
  )
}
