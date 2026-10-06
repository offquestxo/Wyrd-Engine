"use client"

import { FlaskConicalIcon, Loader2Icon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { LivePlanCard } from "@/components/plans/live-plan-card"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { api } from "@/lib/api"
import type { PlanRecord } from "@/lib/types"

/** Proposes a plan with the @demo test agent, so the job pipeline can be tried end to end. */
export function TestRunButton() {
  const [plan, setPlan] = useState<PlanRecord | null>(null)
  const [creating, setCreating] = useState(false)

  const propose = async () => {
    setCreating(true)
    try {
      setPlan(
        await api<PlanRecord>("/api/plans", {
          method: "POST",
          body: JSON.stringify({
            summary: "Test run with the demo agent",
            steps: [{ agent: "demo", params: { steps: 8, step_seconds: 1.5 } }],
          }),
        }),
      )
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => void propose()} disabled={creating}>
        {creating ? <Loader2Icon className="animate-spin" /> : <FlaskConicalIcon />} Test run
      </Button>
      <PlanDialog plan={plan} onOpenChange={(open) => !open && setPlan(null)} onChange={setPlan} />
    </>
  )
}

export function PlanDialog({
  plan,
  onOpenChange,
  onChange,
}: {
  plan: PlanRecord | null
  onOpenChange: (open: boolean) => void
  onChange: (plan: PlanRecord) => void
}) {
  return (
    <Dialog open={!!plan} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Review plan</DialogTitle>
          <DialogDescription>Nothing runs until you approve.</DialogDescription>
        </DialogHeader>
        {plan && (
          <LivePlanCard
            plan={plan}
            onChange={(next) => {
              onChange(next)
              if (next.status !== "pending") onOpenChange(false)
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
