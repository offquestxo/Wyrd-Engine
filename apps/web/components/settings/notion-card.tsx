"use client"

import { CheckCircle2Icon, Loader2Icon, RefreshCwIcon, TriangleAlertIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { useEngineEvent } from "@/hooks/use-events"
import { api, fetcher } from "@/lib/api"
import { timeAgo } from "@/lib/format"
import type { NotionStatus, NotionSyncReport } from "@/lib/types"

const PROPERTIES = [
  ["Title", "title"],
  ["Status", "select"],
  ["Series", "select"],
  ["Format", "select"],
  ["Hook", "text"],
  ["Scores", "text"],
  ["Gap Score", "number"],
  ["Sources", "text"],
  ["Updated", "date"],
  ["Notes", "text"],
  ["Engine ID", "number"],
] as const

/** Optional Notion mirror of Stories (SPEC §8): SQLite stays the source of truth. */
export function NotionCard() {
  const { data, error, isLoading, mutate } = useSWR<NotionStatus>("/api/notion", fetcher)
  const [syncing, setSyncing] = useState(false)
  useEngineEvent(["notion.sync"], () => void mutate())

  if (isLoading) return <LoadingState rows={4} />
  if (error) return <ErrorState error={error as Error} onRetry={() => mutate()} />
  if (!data) return null

  const syncNow = async () => {
    setSyncing(true)
    try {
      const report = await api<NotionSyncReport>("/api/notion/sync", { method: "POST" })
      if (report.ok)
        toast.success("Notion synced", {
          description: `${report.created} created · ${report.updated} updated · ${report.pulled.length} pulled from Notion`,
        })
      else toast.error("Notion sync had problems", { description: report.errors[0] })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSyncing(false)
      void mutate()
    }
  }

  const toggle = async (on: boolean) => {
    try {
      await mutate(await api<NotionStatus>("/api/notion/auto-sync", { method: "PUT", body: JSON.stringify({ auto_sync: on }) }), {
        revalidate: false,
      })
      toast.success(`Notion auto-sync ${on ? "on" : "off"}`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const last = data.last_sync
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Optional mirror of the Stories table. SQLite stays the source of truth: stories push to Notion, and only{" "}
        <span className="text-foreground">Status</span> and <span className="text-foreground">Notes</span> come back
        (the newest change wins). Without a token, nothing here runs and the app works as usual.
      </p>
      <div className="divide-y rounded-lg border text-sm">
        <Row label="NOTION_TOKEN">
          <SetBadge ok={data.token_set} />
        </Row>
        <Row label="NOTION_DATABASE_ID">
          <SetBadge ok={data.database_set} />
        </Row>
        <Row label="Stories linked to Notion pages">
          <span className="font-mono text-xs">
            {data.linked}/{data.stories}
            {data.pending > 0 && <span className="text-muted-foreground"> · {data.pending} to push</span>}
          </span>
        </Row>
        <Row label="Auto-sync (push after changes, pull every 10 min)">
          <Switch checked={data.auto_sync} onCheckedChange={(on) => void toggle(on)} disabled={!data.configured} aria-label="Auto-sync" />
        </Row>
        <Row label={last ? `Last sync ${timeAgo(last.finished_at ?? last.started_at)}` : "Never synced"}>
          <Button size="sm" variant="outline" disabled={!data.configured || syncing || data.syncing} onClick={() => void syncNow()}>
            {syncing || data.syncing ? <Loader2Icon className="animate-spin" /> : <RefreshCwIcon />} Sync now
          </Button>
        </Row>
      </div>

      {last && (
        <div className="space-y-1 rounded-lg border px-4 py-3 text-xs">
          <p className="flex items-center gap-1.5 font-medium">
            {last.ok ? <CheckCircle2Icon className="size-3.5 text-success" /> : <TriangleAlertIcon className="size-3.5 text-warning" />}
            {last.ok ? "Last sync OK" : "Last sync had problems"}
            <span className="font-normal text-muted-foreground">
              · {last.created} created · {last.updated} updated · {last.unchanged} unchanged · {last.pulled.length} pulled ·{" "}
              {last.requests} requests
            </span>
          </p>
          {last.pulled.map((p) => (
            <p key={p.story_id} className="text-muted-foreground">
              From Notion: #{p.story_id} {p.title} → {Object.entries(p.to).map(([k, v]) => `${k} “${v ?? ""}”`).join(", ")}
            </p>
          ))}
          {last.errors.map((e, i) => (
            <p key={i} className="text-destructive">
              {e}
            </p>
          ))}
        </div>
      )}

      {!data.configured && (
        <div className="space-y-2 rounded-lg border px-4 py-3 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">Set up</p>
          <ol className="ml-4 list-decimal space-y-1">
            <li>
              Create an internal integration at notion.so/profile/integrations and copy its token into{" "}
              <code className="font-mono">NOTION_TOKEN</code> in <code className="font-mono">.env</code>.
            </li>
            <li>Create the stories database with these properties (exact names and types):</li>
          </ol>
          <div className="ml-4 flex flex-wrap gap-1.5">
            {PROPERTIES.map(([name, kind]) => (
              <Badge key={name} variant="outline" className="font-mono text-[10px]">
                {name}: {kind}
              </Badge>
            ))}
          </div>
          <ol start={3} className="ml-4 list-decimal space-y-1">
            <li>In the database&apos;s ••• menu → Connections, add your integration.</li>
            <li>
              Put the database ID in <code className="font-mono">NOTION_DATABASE_ID</code>, then Settings → System → Reload .env.
            </li>
          </ol>
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">Notion API version {data.version}; requests are paced to stay under Notion&apos;s rate limit.</p>
    </div>
  )
}

function SetBadge({ ok }: { ok: boolean }) {
  return (
    <Badge variant="outline" className={ok ? "border-success/40 text-success" : "text-muted-foreground"}>
      {ok ? "set" : "missing"}
    </Badge>
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
