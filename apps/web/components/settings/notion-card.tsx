"use client"

import { RefreshCwIcon } from "lucide-react"
import useSWR from "swr"

import { ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { fetcher } from "@/lib/api"
import type { KeyStatus } from "@/lib/types"

export function NotionCard() {
  const { data, error, isLoading, mutate } = useSWR<KeyStatus[]>("/api/keys", fetcher)
  if (isLoading) return <LoadingState rows={3} />
  if (error) return <ErrorState error={error as Error} onRetry={() => mutate()} />
  const notion = data?.filter((k) => k.env.startsWith("NOTION_")) ?? []
  const ready = notion.every((k) => k.status === "set")

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Optional mirror of the Stories table. SQLite stays the source of truth; only Status and Notes sync back from Notion.
        Sync arrives in Phase 7.
      </p>
      <div className="divide-y rounded-lg border text-sm">
        {notion.map((k) => (
          <div key={k.env} className="flex items-center justify-between px-4 py-3">
            <span className="font-mono text-xs">{k.env}</span>
            <Badge variant="outline" className={k.status === "set" ? "border-success/40 text-success" : "text-muted-foreground"}>
              {k.status}
            </Badge>
          </div>
        ))}
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-muted-foreground">Auto-sync after story changes</span>
          <Switch disabled aria-label="Auto-sync (Phase 7)" />
        </div>
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-muted-foreground">{ready ? "Ready to sync" : "Add NOTION_TOKEN and NOTION_DATABASE_ID to .env"}</span>
          <Button size="sm" variant="outline" disabled><RefreshCwIcon /> Sync now</Button>
        </div>
      </div>
    </div>
  )
}
