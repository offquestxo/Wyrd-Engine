"use client"

import { ArrowRightIcon, CheckIcon, ClipboardCheckIcon, Loader2Icon } from "lucide-react"
import Link from "next/link"
import { useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { ParamChips, StepEditor } from "@/components/plans/live-plan-card"
import { Kbd } from "@/components/common/kbd"
import { Button } from "@/components/ui/button"
import { api, fetcher } from "@/lib/api"
import type { AgentSettings, PlanRecord, PlanStepRecord } from "@/lib/types"
import { cn } from "@/lib/utils"

type Params = Record<string, unknown>

const PROVIDER_LABEL: Record<string, string> = {
  groq: "Groq",
  gemini: "Gemini",
  mistral: "Mistral",
  nvidia: "NVIDIA",
  openrouter: "OpenRouter",
  claude: "Claude",
}

/** Model providers a step may use (primary first), without the YouTube quota pseudo-provider. */
function providers(steps: PlanStepRecord[]): string[] {
  const seen = new Set<string>()
  for (const step of steps) for (const p of step.providers ?? []) if (p !== "youtube") seen.add(PROVIDER_LABEL[p] ?? p)
  return [...seen]
}

function youtubeUnits(steps: PlanStepRecord[]): number {
  return steps.reduce((n, s) => n + (s.estimate?.youtube_units ?? 0), 0)
}

const STATUS_PILL: Record<PlanRecord["status"], { text: string; className: string }> = {
  pending: { text: "Waiting for you", className: "bg-brand-muted text-brand-soft" },
  approved: { text: "Running", className: "bg-live/12 text-live-text" },
  done: { text: "Done", className: "bg-success/12 text-success-text" },
  failed: { text: "Failed", className: "bg-destructive/12 text-destructive-text" },
  cancelled: { text: "Cancelled", className: "bg-muted text-subtle-foreground" },
}

const STEP_STATUS: Record<string, string> = {
  running: "text-live-text",
  succeeded: "text-success-text",
  failed: "text-destructive-text",
}

/**
 * Plan card v2 (SPEC §5.3): numbered steps with param chips, providers, YouTube units and
 * whether it uses Claude; Cancel / Edit (inline form) / Approve & run. ⌘⏎ (Ctrl+Enter)
 * approves the focused card. `compact` is the Home approval strip (style A); `creative` is
 * the Chat look (big Bricolage step numbers).
 */
export function PlanCard({
  plan,
  variant = "creative",
  onChange,
  className,
}: {
  plan: PlanRecord
  variant?: "compact" | "creative"
  onChange?: (plan: PlanRecord) => void
  className?: string
}) {
  const { data: agents } = useSWR<AgentSettings[]>("/api/agents", fetcher, { revalidateOnFocus: false })
  const [editing, setEditing] = useState(false)
  const [edits, setEdits] = useState<Record<number, Params>>({})
  const [busy, setBusy] = useState<"approve" | "cancel" | null>(null)
  const ref = useRef<HTMLElement>(null)
  const pending = plan.status === "pending"

  const act = async (kind: "approve" | "cancel") => {
    if (busy) return
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

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (pending && e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void act("approve")
    }
  }

  const describe = (agent: string) => agents?.find((a) => a.name === agent)?.description
  const usesClaude = plan.steps.some((s) => s.uses_claude)
  const units = youtubeUnits(plan.steps)
  const chips = [
    plan.steps.map((s) => `@${s.agent}`).join(" → "),
    providers(plan.steps).join(" · "),
    units > 0 ? `~${units} YouTube units` : null,
    usesClaude ? "uses Claude" : "no Claude usage",
  ].filter(Boolean) as string[]
  const pill = STATUS_PILL[plan.status]

  const actions = (
    <div className="flex flex-wrap items-center gap-2">
      {pending ? (
        <>
          <Button variant="ghost" className="h-11 text-muted-foreground" disabled={busy !== null} onClick={() => void act("cancel")}>
            Cancel
          </Button>
          <Button variant="outline" className="h-11" disabled={busy !== null} onClick={() => setEditing(!editing)}>
            {editing ? "Done editing" : "Edit"}
          </Button>
          <Button
            className={cn(
              "h-11 gap-2 bg-brand px-[18px] text-brand-foreground shadow-[0_6px_22px_rgb(124_58_237/0.4)] hover:bg-brand/90",
              variant === "creative" && "font-display text-base font-extrabold",
            )}
            disabled={busy !== null}
            onClick={() => void act("approve")}
          >
            {busy === "approve" ? <Loader2Icon className="animate-spin" /> : <CheckIcon />}
            Approve &amp; run
            <Kbd className="border-0 bg-white/20 font-sans text-[11px] font-normal text-white">⌘⏎</Kbd>
          </Button>
        </>
      ) : plan.status === "approved" ? (
        <Button variant="ghost" className="h-11 text-muted-foreground" disabled={busy !== null} onClick={() => void act("cancel")}>
          Stop plan
        </Button>
      ) : null}
    </div>
  )

  if (variant === "compact") {
    return (
      <section
        ref={ref}
        tabIndex={0}
        onKeyDown={onKeyDown}
        aria-label={`Plan ${plan.id}`}
        className={cn(
          "flex flex-wrap items-center gap-4 rounded-xl border bg-card px-[18px] py-4 outline-none focus-visible:ring-2 focus-visible:ring-ring",
          pending && "border-transparent bg-[#120f1e] glow-brand",
          className,
        )}
      >
        <div className="flex size-10 shrink-0 items-center justify-center rounded-[10px] bg-brand/20 text-brand-soft">
          <ClipboardCheckIcon className="size-5" />
        </div>
        <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-1.5">
          <span className="font-mono text-[11px] tracking-[1px] text-brand-soft uppercase">
            Plan #{plan.id} · {pending ? "needs your OK" : pill.text}
          </span>
          <span className="text-[15.5px] font-medium">{plan.summary ?? plan.steps.map((s) => `@${s.agent}`).join(", ")}</span>
          <div className="flex flex-wrap gap-1.5 font-mono text-[11.5px] text-muted-foreground">
            {chips.map((c) => (
              <span key={c} className="rounded-md bg-secondary px-2 py-[3px]">
                {c}
              </span>
            ))}
          </div>
          {editing && <Steps plan={plan} edits={edits} setEdits={setEdits} editing describe={describe} variant="compact" />}
        </div>
        {actions}
      </section>
    )
  }

  return (
    <section
      ref={ref}
      tabIndex={0}
      onKeyDown={onKeyDown}
      aria-label={`Plan ${plan.id}`}
      className={cn(
        "flex flex-col gap-3.5 rounded-[20px] border border-white/9 bg-card-creative p-[18px] text-foreground-warm outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <h2 className="font-display text-[22px] font-extrabold tracking-[-0.4px]">Plan #{plan.id}</h2>
        <span className={cn("rounded-full px-2.5 py-1 text-[12.5px]", pill.className)}>{pill.text}</span>
        {plan.summary && <span className="min-w-0 truncate text-sm text-muted-foreground">{plan.summary}</span>}
      </div>
      <Steps plan={plan} edits={edits} setEdits={setEdits} editing={editing} describe={describe} variant="creative" />
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex-[1_1_200px] text-[12.5px] text-subtle-foreground">
          {usesClaude ? "Uses Claude" : "No Claude usage"}
          {units > 0 ? ` · ~${units} YouTube units` : ""}
        </span>
        {actions}
      </div>
    </section>
  )
}

function Steps({
  plan,
  edits,
  setEdits,
  editing,
  describe,
  variant,
}: {
  plan: PlanRecord
  edits: Record<number, Params>
  setEdits: (e: Record<number, Params>) => void
  editing: boolean
  describe: (agent: string) => string | undefined
  variant: "compact" | "creative"
}) {
  return (
    <ol className={cn("grid gap-3", variant === "creative" && "grid-cols-[repeat(auto-fit,minmax(260px,1fr))]")}>
      {plan.steps.map((step) => {
        const params = edits[step.order] ?? step.params ?? {}
        const meta = [
          (step.providers ?? []).filter((p) => p !== "youtube").map((p) => PROVIDER_LABEL[p] ?? p).join(" → "),
          step.estimate?.youtube_units ? `~${step.estimate.youtube_units} units` : "0 units",
          step.uses_claude ? `Claude${step.estimate?.claude_turns ? ` · up to ${step.estimate.claude_turns} turns` : ""}` : "no Claude",
        ]
        return (
          <li key={step.id} className={cn("flex flex-col gap-3 rounded-[14px] p-4", variant === "creative" ? "bg-[#1c1f29]" : "bg-secondary/60")}>
            <div className="flex items-center gap-3">
              <span className={cn("font-display leading-none font-extrabold", variant === "creative" ? "text-[34px]" : "text-2xl")}>
                {String(step.order).padStart(2, "0")}
              </span>
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="font-mono text-sm font-semibold">@{step.agent}</span>
                {describe(step.agent) && <span className="truncate text-[13px] text-muted-foreground">{describe(step.agent)}</span>}
              </div>
              <span className={cn("ml-auto font-mono text-[11px] uppercase", STEP_STATUS[step.status] ?? "text-subtle-foreground")}>
                {step.status}
              </span>
            </div>
            {editing ? (
              <StepEditor step={step} value={params} onChange={(p) => setEdits({ ...edits, [step.order]: p })} />
            ) : (
              <ParamChips params={params} />
            )}
            <span className="text-[12.5px] text-muted-foreground">{meta.filter(Boolean).join(" · ")}</span>
            {step.run_id && (
              <Link href={`/runs/${step.run_id}`} className="font-mono text-[11px] text-brand-soft hover:underline">
                run #{step.run_id} <ArrowRightIcon className="inline size-3" />
              </Link>
            )}
          </li>
        )
      })}
    </ol>
  )
}
