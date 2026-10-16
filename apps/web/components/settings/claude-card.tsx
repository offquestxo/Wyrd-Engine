"use client"

import { SparklesIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { ErrorState, LoadingState } from "@/components/common/states"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ClaudeStatusPanel } from "@/components/settings/claude-status"
import { api, fetcher } from "@/lib/api"

interface ClaudeSettings {
  soft_cap: number
  default_soft_cap: number
  model: string
  effort: string | null
  tools: string[]
}

/** Claude usage soft cap (SPEC §4.2). Pro plan usage isn't exposed, so the engine counts
 *  its own Claude calls per day and warns as they near this cap. */
export function ClaudeCard() {
  const { data, error, isLoading, mutate } = useSWR<ClaudeSettings>("/api/settings/claude", fetcher)
  const [draft, setDraft] = useState<string | null>(null)
  const value = draft ?? String(data?.soft_cap ?? "")

  const save = async () => {
    try {
      const next = await api<ClaudeSettings>("/api/settings/claude", {
        method: "PUT",
        body: JSON.stringify({ soft_cap: Number(value) }),
      })
      await mutate(next, { revalidate: false })
      setDraft(null)
      toast.success(`Claude soft cap set to ${next.soft_cap} calls a day`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (isLoading) return <LoadingState rows={2} />
  if (error) return <ErrorState error={error as Error} onRetry={() => mutate()} />
  if (!data) return null
  return (
    <section className="space-y-3 rounded-lg border p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <SparklesIcon className="size-4 text-brand-soft" /> Claude
      </div>
      <ClaudeStatusPanel />
      <p className="text-xs text-muted-foreground">
        Your Pro plan is shared with other Claude use, and its usage isn&apos;t readable by apps. The engine counts its own
        Claude calls (chat turns plus Claude agent runs) per day and warns at 80% of this soft cap. Nothing is blocked.
      </p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          void save()
        }}
      >
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Daily soft cap (calls)</span>
          <Input type="number" min={1} max={1000} className="h-8 w-28" value={value} onChange={(e) => setDraft(e.target.value)} />
        </label>
        <Button size="sm" type="submit" disabled={draft === null || !Number(value)}>
          Save
        </Button>
        <span className="pb-1.5 text-[11px] text-muted-foreground">Default {data.default_soft_cap} (engine.yaml)</span>
      </form>
      <p className="text-[11px] text-muted-foreground">
        Orchestrator: <span className="font-mono">{data.model}</span>
        {data.effort && (
          <>
            {" "}
            · effort <span className="font-mono">{data.effort}</span>
          </>
        )}{" "}
        · tools: <span className="font-mono">{data.tools.map((t) => t.replace("mcp__wyrd__", "")).join(", ")}</span> (no shell, no file edits)
      </p>
    </section>
  )
}
