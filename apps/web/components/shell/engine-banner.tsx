"use client"

import { AlertTriangleIcon, PlugZapIcon } from "lucide-react"
import useSWR from "swr"

import { fetcher } from "@/lib/api"
import type { ClaudeStatus } from "@/lib/types"

/** Top banner when the API is unreachable or the Claude CLI isn't ready (SPEC §10). */
export function EngineBanner() {
  const { data, error } = useSWR<{ ok: boolean; claude: ClaudeStatus | null }>("/api/health", fetcher, {
    refreshInterval: 30_000,
  })

  if (error) {
    return (
      <Banner icon={PlugZapIcon} tone="destructive">
        Can&apos;t reach the engine API on 127.0.0.1:8000. Start it with <code className="font-mono">make dev</code>.
      </Banner>
    )
  }
  const claude = data?.claude
  if (claude && (!claude.installed || !claude.logged_in)) {
    return (
      <Banner icon={AlertTriangleIcon} tone="warning">
        {claude.detail} The orchestrator and @researcher need it (Phase 5+).
      </Banner>
    )
  }
  return null
}

function Banner({
  icon: Icon,
  tone,
  children,
}: {
  icon: typeof PlugZapIcon
  tone: "warning" | "destructive"
  children: React.ReactNode
}) {
  const styles =
    tone === "warning"
      ? "border-warning/20 bg-warning/5 text-warning"
      : "border-destructive/20 bg-destructive/5 text-destructive"
  return (
    <div role="status" className={`flex items-center gap-2 border-b px-6 py-2 text-xs ${styles}`}>
      <Icon className="size-3.5 shrink-0" />
      <span className="text-foreground/80">{children}</span>
    </div>
  )
}
