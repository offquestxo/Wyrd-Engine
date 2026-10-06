"use client"

import { ArrowRightIcon, CheckCircle2Icon, CircleAlertIcon, CircleSlashIcon } from "lucide-react"
import Link from "next/link"

import { AgentTag } from "@/components/common/badges"
import type { ChatMessageRecord, ResultStep } from "@/lib/types"
import { cn } from "@/lib/utils"

const VIEW: Record<string, { href: string; label: string }> = {
  scout: { href: "/stories", label: "Stories" },
  outlier: { href: "/outliers", label: "Outliers" },
}

/** Compact results of a finished plan, each step linking to its full view (SPEC §9 Chat). */
export function ResultCard({ message }: { message: ChatMessageRecord }) {
  const steps = message.metadata.steps ?? []
  return (
    <div className="space-y-2">
      <p className="font-mono text-[11px] text-muted-foreground">
        Plan #{message.metadata.plan_id} {message.metadata.status}
      </p>
      {steps.map((step) => (
        <StepResult key={step.order} step={step} />
      ))}
    </div>
  )
}

function StepResult({ step }: { step: ResultStep }) {
  const ok = step.status === "succeeded"
  const Icon = ok ? CheckCircle2Icon : step.status === "cancelled" || step.status === "skipped" ? CircleSlashIcon : CircleAlertIcon
  const view = VIEW[step.agent]
  return (
    <div className="rounded-lg border bg-card p-3 sm:p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Icon className={cn("size-3.5", ok ? "text-success" : step.status === "failed" ? "text-destructive" : "text-muted-foreground")} />
        <AgentTag agent={step.agent} />
        <span className="min-w-0 flex-1 text-sm">{step.summary ?? step.status}</span>
      </div>
      {step.error && <p className="mt-1 text-xs text-destructive">{step.error}</p>}
      {step.items.length > 0 && (
        <ul className="mt-2 space-y-1">
          {step.items.map((item, i) => (
            <li key={`${item.id ?? i}`}>
              <Link href={item.href} className="group flex items-baseline gap-2 text-xs hover:text-foreground">
                <span className="min-w-0 truncate text-foreground/90 group-hover:underline">{item.label}</span>
                {item.detail && <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{item.detail}</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11px] text-muted-foreground">
        {step.run_id && (
          <Link href={`/runs/${step.run_id}`} className="hover:text-brand">
            run #{step.run_id}
          </Link>
        )}
        {step.youtube_units != null && <span>{step.youtube_units} YouTube units</span>}
        {view && ok && (
          <Link href={view.href} className="ml-auto flex items-center gap-1 text-brand hover:underline">
            Open {view.label} <ArrowRightIcon className="size-3" />
          </Link>
        )}
      </div>
    </div>
  )
}
