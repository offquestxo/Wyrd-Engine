"use client"

import { BotIcon, SparklesIcon } from "lucide-react"
import { toast } from "sonner"
import useSWR from "swr"

import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { api, fetcher } from "@/lib/api"
import type { AgentSettings } from "@/lib/types"

export function AgentsCard() {
  const { data, error, isLoading, mutate } = useSWR<AgentSettings[]>("/api/agents", fetcher)

  const toggle = async (agent: AgentSettings, on: boolean) => {
    await mutate(data?.map((a) => (a.name === agent.name ? { ...a, auto_approve: on } : a)), { revalidate: false })
    try {
      await api(`/api/agents/${agent.name}/auto-approve`, { method: "PUT", body: JSON.stringify({ auto_approve: on }) })
      toast.success(`@${agent.name} auto-approve ${on ? "on" : "off"}`)
    } catch (e) {
      toast.error((e as Error).message)
    }
    await mutate()
  }

  if (isLoading) return <LoadingState rows={5} />
  if (error) return <ErrorState error={error as Error} onRetry={() => mutate()} />
  if (!data?.length) return <EmptyState icon={BotIcon} title="No agents registered" />

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Every run is proposed as a plan card for you to approve. Auto-approve skips that step for one agent. Off by default.
      </p>
      <div className="divide-y rounded-lg border">
        {data.map((agent) => (
          <div key={agent.name} className="flex items-center gap-4 px-4 py-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm text-brand-soft">@{agent.name}</span>
                {agent.uses_claude && <Badge variant="outline" className="gap-1 text-[10px]"><SparklesIcon className="size-3" /> Claude</Badge>}
                {agent.uses_youtube_quota && <Badge variant="outline" className="text-[10px]">YouTube quota</Badge>}
                {!agent.available && <Badge variant="outline" className="text-[10px] text-muted-foreground">v2</Badge>}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">{agent.description}</p>
            </div>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              Auto-approve
              <Switch
                checked={agent.auto_approve}
                disabled={!agent.available}
                onCheckedChange={(on) => void toggle(agent, on)}
                aria-label={`Auto-approve @${agent.name}`}
              />
            </label>
          </div>
        ))}
      </div>
    </div>
  )
}
