"use client"

import { ActivityIcon, ArrowRightIcon, ClipboardListIcon, GaugeIcon } from "lucide-react"
import { useState } from "react"

import { PageHeader } from "@/components/common/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { PlanDialog, TestRunButton } from "@/components/plans/test-run-dialog"
import { RunRow } from "@/components/runs/run-row"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { usePlans, useRuns, useUsage } from "@/hooks/use-live"
import { formatNumber } from "@/lib/format"
import type { PlanRecord, ProviderMeter } from "@/lib/types"
import { cn } from "@/lib/utils"

export function HomeView() {
  const runs = useRuns("limit=12")
  const usage = useUsage()
  const pending = usePlans("pending")
  const [reviewing, setReviewing] = useState<PlanRecord | null>(null)

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <PageHeader
        title="Home"
        description="What the agents are doing and how much quota is left today."
        actions={<TestRunButton />}
      />

      {pending.data && pending.data.length > 0 && (
        <div className="mb-6 overflow-hidden rounded-lg border border-brand/30 bg-brand-muted">
          {pending.data.slice(0, 3).map((plan) => (
            <button
              key={plan.id}
              onClick={() => setReviewing(plan)}
              className="flex w-full items-center gap-3 border-b border-brand/20 px-4 py-3 text-left text-sm transition-colors last:border-b-0 hover:bg-brand/10"
            >
              <ClipboardListIcon className="size-4 text-brand" />
              <span className="flex-1 truncate">
                <span className="font-medium">Plan #{plan.id} waiting for approval</span>
                <span className="text-muted-foreground"> · {plan.summary}</span>
              </span>
              <span className="flex items-center gap-1 text-xs text-brand">
                Review <ArrowRightIcon className="size-3" />
              </span>
            </button>
          ))}
          {pending.data.length > 3 && (
            <p className="px-4 py-2 text-xs text-muted-foreground">+{pending.data.length - 3} more pending</p>
          )}
        </div>
      )}
      <PlanDialog
        plan={reviewing}
        onOpenChange={(open) => !open && setReviewing(null)}
        onChange={(plan) => {
          setReviewing(plan)
          void pending.mutate()
        }}
      />

      <section className="mb-8">
        <SectionTitle icon={ActivityIcon}>Live agent activity</SectionTitle>
        {runs.isLoading ? (
          <LoadingState rows={4} />
        ) : runs.error ? (
          <ErrorState error={runs.error as Error} onRetry={() => void runs.mutate()} />
        ) : !runs.data?.length ? (
          <EmptyState
            icon={ActivityIcon}
            title="No runs yet"
            description="Approve a plan to start an agent. Try “Test run” to watch the pipeline work."
            action={<TestRunButton />}
          />
        ) : (
          <div className="overflow-hidden rounded-lg border">
            {runs.data.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </div>
        )}
      </section>

      <section>
        <SectionTitle icon={GaugeIcon}>
          API usage today
          {usage.data && (
            <span className="font-normal text-muted-foreground/70">
              {" "}
              · since midnight {usage.data.timezone.split("/").pop()?.replace("_", " ")}
            </span>
          )}
        </SectionTitle>
        {usage.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <LoadingState key={i} rows={1} className="[&>*]:h-32" />
            ))}
          </div>
        ) : usage.error ? (
          <ErrorState error={usage.error as Error} onRetry={() => void usage.mutate()} />
        ) : !usage.data?.meters.length ? (
          <EmptyState icon={GaugeIcon} title="No providers configured" />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {usage.data.meters.map((meter) => (
              <MeterCard key={meter.provider} meter={meter} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function SectionTitle({ icon: Icon, children }: { icon: typeof ActivityIcon; children: React.ReactNode }) {
  return (
    <h2 className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
      <Icon className="size-4" /> {children}
    </h2>
  )
}

const STATUS_DOT: Record<string, string> = {
  set: "bg-success",
  failing: "bg-destructive",
  missing: "bg-muted-foreground/40",
  disabled: "border border-subtle-foreground bg-transparent",
}

function MeterCard({ meter }: { meter: ProviderMeter }) {
  const pct = meter.limit ? Math.min(100, (meter.used / meter.limit) * 100) : null
  const tone = pct === null ? "bg-info" : pct >= 80 ? "bg-destructive" : pct >= 60 ? "bg-warning" : "bg-brand"
  const statusLabel =
    meter.status === "missing" ? "No key" : meter.status === "failing" ? "Key failing" : meter.status === "disabled" ? "Disabled in providers.yaml" : "Connected"
  return (
    <Card className={cn("gap-3 py-4", (meter.status === "missing" || meter.status === "disabled") && "opacity-60")}>
      <CardHeader className="px-4">
        <CardTitle className="flex items-center justify-between text-sm">
          {meter.label}
          <Tooltip>
            <TooltipTrigger asChild>
              <span className={cn("size-1.5 rounded-full", STATUS_DOT[meter.status] ?? "bg-success")} />
            </TooltipTrigger>
            <TooltipContent>{statusLabel}</TooltipContent>
          </Tooltip>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 px-4">
        <p className="font-mono text-lg tabular-nums">
          {formatNumber(meter.used)}
          <span className="text-xs text-muted-foreground">
            {" "}
            / {meter.limit ? formatNumber(meter.limit) : "∞"} {meter.unit}
          </span>
        </p>
        <div className="h-1 overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full rounded-full transition-all", tone)}
            style={{ width: `${pct ?? 100}%`, opacity: pct === null ? 0.25 : 1 }}
          />
        </div>
        <p className="font-mono text-[10px] text-muted-foreground">
          {formatNumber(meter.requests)} calls · {meter.errors} err · {meter.fallbacks} fallback
        </p>
        {meter.claude && (
          <div className="space-y-0.5 font-mono text-[10px] text-muted-foreground">
            <p>
              {meter.claude.chat_turns} chat · {meter.claude.agent_runs} agent runs · {meter.claude.turns} turns ·{" "}
              {meter.claude.duration_s}s
            </p>
            {(meter.claude.warn || meter.claude.over) && (
              <p className={meter.claude.over ? "text-destructive" : "text-warning"}>
                {meter.claude.over ? "Over the daily soft cap" : "Nearing the daily soft cap"} (Settings → Agents)
              </p>
            )}
            {meter.claude.rate_limit?.status && meter.claude.rate_limit.status !== "allowed" && (
              <p className="text-warning">Claude Code reports: {meter.claude.rate_limit.status}</p>
            )}
          </div>
        )}
        {meter.search_limit ? (
          <p className="font-mono text-[10px] text-muted-foreground">
            search {meter.search_calls ?? 0} / {meter.search_limit} calls
          </p>
        ) : null}
        {meter.models.some((m) => m.requests > 0) && (
          <ul className="space-y-0.5 border-t pt-2 font-mono text-[10px] text-muted-foreground">
            {meter.models
              .filter((m) => m.requests > 0)
              .map((m) => (
                <li key={m.alias} className="flex justify-between gap-2">
                  <span className="truncate">{m.alias}</span>
                  <span>
                    {m.requests}
                    {m.limits.rpd ? `/${formatNumber(m.limits.rpd)}` : ""} · {formatNumber(m.tokens)} tok
                  </span>
                </li>
              ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
