"use client"

// App-wide "propose a plan" flow: anything can ask to run an agent; the owner reviews the
// plan card (and can edit params) before anything runs.

import { createContext, type ReactNode, useCallback, useContext, useState } from "react"
import { toast } from "sonner"

import { PlanDialog } from "@/components/plans/test-run-dialog"
import { api } from "@/lib/api"
import type { PlanRecord } from "@/lib/types"

type Propose = (agent: string, params: Record<string, unknown>, summary: string) => Promise<void>

const ProposeContext = createContext<Propose>(async () => {})

export function ProposeProvider({ children }: { children: ReactNode }) {
  const [plan, setPlan] = useState<PlanRecord | null>(null)

  const propose = useCallback<Propose>(async (agent, params, summary) => {
    try {
      const created = await api<PlanRecord>("/api/plans", {
        method: "POST",
        body: JSON.stringify({ summary, steps: [{ agent, params }] }),
      })
      if (created.status === "pending") setPlan(created)
      else toast.success(`Plan #${created.id} auto-approved`, { description: `@${agent} is running.` })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }, [])

  return (
    <ProposeContext.Provider value={propose}>
      {children}
      <PlanDialog plan={plan} onOpenChange={(open) => !open && setPlan(null)} onChange={setPlan} />
    </ProposeContext.Provider>
  )
}

export const useProposePlan = () => useContext(ProposeContext)
