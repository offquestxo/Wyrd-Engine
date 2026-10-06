"use client"

import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { PageHeader } from "@/components/common/page-header"
import { AgentsCard } from "@/components/settings/agents-card"
import { ClaudeCard } from "@/components/settings/claude-card"
import { ConfigEditor } from "@/components/settings/config-editor"
import { KeysCard } from "@/components/settings/keys-card"
import { NotionCard } from "@/components/settings/notion-card"
import { ProvidersCard } from "@/components/settings/providers-card"
import { SystemCard } from "@/components/settings/system-card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

const TABS = [
  { id: "keys", label: "API keys" },
  { id: "providers", label: "Providers & quotas" },
  { id: "agents", label: "Agents" },
  { id: "sources", label: "Scout sources" },
  { id: "channels", label: "Channels" },
  { id: "scoring", label: "Scoring" },
  { id: "engine", label: "Engine" },
  { id: "notion", label: "Notion" },
  { id: "system", label: "System" },
] as const

export function SettingsView() {
  const router = useRouter()
  const pathname = usePathname()
  const tab = useSearchParams().get("tab") ?? "keys"

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
      <PageHeader title="Settings" description="Keys, providers, agents, and the config files in config/." />
      <Tabs value={tab} onValueChange={(t) => router.replace(`${pathname}?tab=${t}`, { scroll: false })}>
        <TabsList className="mb-6 flex-wrap">
          {TABS.map((t) => <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>)}
        </TabsList>
        <TabsContent value="keys"><KeysCard /></TabsContent>
        <TabsContent value="providers"><ProvidersCard /></TabsContent>
        <TabsContent value="agents" className="space-y-6"><AgentsCard /><ClaudeCard /></TabsContent>
        <TabsContent value="sources">
          <ConfigEditor name="sources" hint="News feeds, queries, Wikipedia categories, request pacing" />
        </TabsContent>
        <TabsContent value="channels">
          <ConfigEditor name="channels" hint="Competitor channels for @outlier" />
        </TabsContent>
        <TabsContent value="scoring">
          <ConfigEditor name="scoring" hint="Dedup threshold, rubric weights, gap and outlier thresholds" />
        </TabsContent>
        <TabsContent value="engine">
          <ConfigEditor name="engine" hint="Concurrent runs, queue polling, quota day reset timezone, orchestrator model and timeout" />
        </TabsContent>
        <TabsContent value="notion"><NotionCard /></TabsContent>
        <TabsContent value="system"><SystemCard /></TabsContent>
      </Tabs>
    </div>
  )
}
