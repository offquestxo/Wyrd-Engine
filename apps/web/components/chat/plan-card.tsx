"use client"

import { CheckIcon, PencilIcon, SparklesIcon, XIcon, MonitorPlayIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { AgentTag } from "@/components/common/badges"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { Plan, PlanStep } from "@/lib/types"

export function PlanCard({ plan }: { plan: Plan }) {
  const [status, setStatus] = useState(plan.status)
  const [editing, setEditing] = useState(false)
  const [steps, setSteps] = useState(plan.steps)
  const totalUnits = steps.reduce((sum, s) => sum + (s.youtube_units ?? 0), 0)

  const decide = (next: "approved" | "cancelled") => {
    setStatus(next)
    setEditing(false)
    toast.info(
      next === "approved"
        ? "Sample plan approved. Real execution is wired up in Phase 5."
        : "Plan cancelled.",
    )
  }

  return (
    <div className="mt-3 overflow-hidden rounded-lg border bg-card">
      <div className="flex items-center justify-between border-b px-4 py-2.5">
        <div className="flex items-center gap-2 text-sm font-medium">
          Plan #{plan.id}
          <Badge variant="outline" className="font-mono text-[10px] uppercase">{status}</Badge>
        </div>
        {totalUnits > 0 && (
          <span className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
            <MonitorPlayIcon className="size-3" /> ~{totalUnits} units
          </span>
        )}
      </div>
      <ol className="divide-y">
        {steps.map((step, i) => (
          <li key={step.order} className="px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">{step.order}.</span>
              <AgentTag agent={step.agent} />
              {step.uses_claude && (
                <Badge variant="outline" className="gap-1 text-[10px]"><SparklesIcon className="size-3" /> Claude</Badge>
              )}
              <span className="ml-auto font-mono text-[11px] text-muted-foreground">{step.providers.join(" · ")}</span>
            </div>
            {editing ? (
              <StepEditor step={step} onChange={(next) => setSteps(steps.map((s, j) => (j === i ? next : s)))} />
            ) : (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(step.params).map(([k, v]) => (
                  <span key={k} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                    <span className="text-muted-foreground">{k}=</span>
                    {Array.isArray(v) ? v.join(",") : String(v)}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ol>
      {status === "pending" && (
        <div className="flex gap-2 border-t bg-muted/30 px-4 py-2.5">
          <Button size="sm" className="bg-brand text-brand-foreground hover:bg-brand/90" onClick={() => decide("approved")}>
            <CheckIcon /> Approve
          </Button>
          <Button size="sm" variant="outline" onClick={() => setEditing(!editing)}>
            <PencilIcon /> {editing ? "Done editing" : "Edit"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => decide("cancelled")}>
            <XIcon /> Cancel
          </Button>
        </div>
      )}
    </div>
  )
}

function StepEditor({ step, onChange }: { step: PlanStep; onChange: (step: PlanStep) => void }) {
  return (
    <div className="mt-3 grid grid-cols-2 gap-2">
      {Object.entries(step.params).map(([key, value]) => (
        <label key={key} className="space-y-1">
          <span className="font-mono text-[11px] text-muted-foreground">{key}</span>
          <Input
            className="h-7 font-mono text-xs"
            defaultValue={Array.isArray(value) ? value.join(",") : String(value)}
            onChange={(e) => {
              const raw = e.target.value
              const parsed = Array.isArray(value)
                ? raw.split(",").map((s) => s.trim()).filter(Boolean)
                : typeof value === "number"
                  ? Number(raw)
                  : raw
              onChange({ ...step, params: { ...step.params, [key]: parsed } })
            }}
          />
        </label>
      ))}
    </div>
  )
}
