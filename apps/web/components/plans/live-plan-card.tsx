"use client"

import { ArrowRightIcon, CheckIcon, Loader2Icon, MonitorPlayIcon, PencilIcon, SparklesIcon, XIcon } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import { toast } from "sonner"

import { AgentTag } from "@/components/common/badges"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import type { PlanRecord, PlanStepRecord } from "@/lib/types"
import { cn } from "@/lib/utils"

const STEP_STYLE: Record<string, string> = {
  pending: "text-muted-foreground",
  queued: "text-muted-foreground",
  running: "text-brand",
  succeeded: "text-success",
  failed: "text-destructive",
  cancelled: "text-muted-foreground",
  skipped: "text-muted-foreground/60",
}

type Params = Record<string, unknown>

/** A real plan from /api/plans with Approve / Edit / Cancel (SPEC §5.3). */
export function LivePlanCard({ plan, onChange }: { plan: PlanRecord; onChange?: (plan: PlanRecord) => void }) {
  const [editing, setEditing] = useState(false)
  const [edits, setEdits] = useState<Record<number, Params>>({})
  const [busy, setBusy] = useState<"approve" | "cancel" | null>(null)

  const act = async (kind: "approve" | "cancel") => {
    setBusy(kind)
    try {
      const body = kind === "approve" && Object.keys(edits).length ? JSON.stringify({ edits }) : undefined
      const next = await api<PlanRecord>(`/api/plans/${plan.id}/${kind}`, { method: "POST", body })
      setEditing(false)
      onChange?.(next)
      toast.success(kind === "approve" ? `Plan #${plan.id} approved` : `Plan #${plan.id} cancelled`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
          <span className="shrink-0">Plan #{plan.id}</span>
          <Badge variant="outline" className="font-mono text-[10px] uppercase">{plan.status}</Badge>
          {plan.summary && <span className="truncate font-normal text-muted-foreground">{plan.summary}</span>}
        </div>
      </div>
      <ol className="divide-y">
        {plan.steps.map((step) => (
          <li key={step.id} className="px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">{step.order}.</span>
              <AgentTag agent={step.agent} />
              {step.uses_claude && (
                <Badge variant="outline" className="gap-1 text-[10px]"><SparklesIcon className="size-3" /> Claude</Badge>
              )}
              {step.uses_youtube_quota && (
                <Badge variant="outline" className="gap-1 text-[10px]"><MonitorPlayIcon className="size-3" /> YouTube quota</Badge>
              )}
              <span className={cn("ml-auto font-mono text-[11px] uppercase", STEP_STYLE[step.status])}>{step.status}</span>
              {step.run_id && (
                <Link href={`/runs/${step.run_id}`} className="font-mono text-[11px] text-brand hover:underline">
                  run #{step.run_id} <ArrowRightIcon className="inline size-3" />
                </Link>
              )}
            </div>
            {editing ? (
              <StepEditor
                step={step}
                value={edits[step.order] ?? step.params ?? {}}
                onChange={(params) => setEdits({ ...edits, [step.order]: params })}
              />
            ) : (
              <ParamChips params={edits[step.order] ?? step.params ?? {}} />
            )}
          </li>
        ))}
      </ol>
      {plan.status === "pending" && (
        <div className="flex gap-2 border-t bg-muted/30 px-4 py-2.5">
          <Button size="sm" disabled={busy !== null} onClick={() => void act("approve")} className="bg-brand text-brand-foreground hover:bg-brand/90">
            {busy === "approve" ? <Loader2Icon className="animate-spin" /> : <CheckIcon />} Approve
          </Button>
          <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => setEditing(!editing)}>
            <PencilIcon /> {editing ? "Done editing" : "Edit"}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void act("cancel")}>
            <XIcon /> Cancel
          </Button>
        </div>
      )}
      {plan.status === "approved" && (
        <div className="flex gap-2 border-t bg-muted/30 px-4 py-2.5">
          <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void act("cancel")}>
            <XIcon /> Stop plan
          </Button>
        </div>
      )}
    </div>
  )
}

function ParamChips({ params }: { params: Params }) {
  const entries = Object.entries(params)
  if (!entries.length) return <p className="mt-2 text-xs text-muted-foreground">Default parameters</p>
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {entries.map(([k, v]) => (
        <span key={k} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
          <span className="text-muted-foreground">{k}=</span>
          {Array.isArray(v) ? v.join(",") : String(v)}
        </span>
      ))}
    </div>
  )
}

function StepEditor({ value, onChange }: { step: PlanStepRecord; value: Params; onChange: (p: Params) => void }) {
  return (
    <div className="mt-3 grid grid-cols-2 gap-2">
      {Object.entries(value).map(([key, current]) => (
        <label key={key} className="space-y-1">
          <span className="font-mono text-[11px] text-muted-foreground">{key}</span>
          <Input
            className="h-7 font-mono text-xs"
            defaultValue={Array.isArray(current) ? current.join(",") : String(current ?? "")}
            onChange={(e) => {
              const raw = e.target.value
              const parsed = Array.isArray(current)
                ? raw.split(",").map((s) => s.trim()).filter(Boolean)
                : typeof current === "number"
                  ? Number(raw)
                  : typeof current === "boolean"
                    ? raw === "true"
                    : raw
              onChange({ ...value, [key]: parsed })
            }}
          />
        </label>
      ))}
    </div>
  )
}
