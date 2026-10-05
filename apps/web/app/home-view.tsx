"use client"

import { ActivityIcon, ArrowRightIcon, CheckCircle2Icon, ClipboardListIcon, GaugeIcon } from "lucide-react"
import Link from "next/link"
import { useEffect, useState } from "react"

import { AgentTag, RunStatusBadge } from "@/components/common/badges"
import { PageHeader } from "@/components/common/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useDemo } from "@/hooks/use-demo"
import { clock, duration, formatNumber, timeAgo } from "@/lib/format"
import { MOCK_PLAN, MOCK_RUNS, MOCK_USAGE } from "@/lib/mock"
import type { AgentRun, UsageMeter } from "@/lib/types"
import { cn } from "@/lib/utils"

export function HomeView() {
  const runs = useDemo(MOCK_RUNS, [])
  const usage = useDemo(MOCK_USAGE, [])
  const plans = useDemo([MOCK_PLAN], [])

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <PageHeader title="Home" description="What the agents are doing and how much quota is left today." sample />

      {plans.data && plans.data.length > 0 && (
        <Link
          href="/chat"
          className="mb-6 flex items-center gap-3 rounded-lg border border-brand/30 bg-brand-muted px-4 py-3 text-sm transition-colors hover:border-brand/50"
        >
          <ClipboardListIcon className="size-4 text-brand" />
          <span className="flex-1">
            <span className="font-medium">{plans.data.length} plan waiting for approval</span>
            <span className="text-muted-foreground"> · {plans.data[0].summary}</span>
          </span>
          <span className="flex items-center gap-1 text-xs text-brand">
            Review <ArrowRightIcon className="size-3" />
          </span>
        </Link>
      )}

      <section className="mb-8">
        <SectionTitle icon={ActivityIcon}>Live agent activity</SectionTitle>
        {runs.isLoading ? (
          <LoadingState rows={4} />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={runs.retry} />
        ) : !runs.data?.length ? (
          <EmptyState
            icon={ActivityIcon}
            title="No runs yet"
            description="Approve a plan in Chat or press ⌘K to start @scout, @outlier, or @researcher."
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
        <SectionTitle icon={GaugeIcon}>API usage today</SectionTitle>
        {usage.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {Array.from({ length: 5 }, (_, i) => (
              <LoadingState key={i} rows={1} className="[&>*]:h-32" />
            ))}
          </div>
        ) : usage.error ? (
          <ErrorState error={usage.error} onRetry={usage.retry} />
        ) : !usage.data?.length ? (
          <EmptyState icon={GaugeIcon} title="No provider calls today" description="Meters fill in as agents call providers." />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {usage.data.map((meter) => (
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

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(t)
  }, [intervalMs])
  return now
}

function RunRow({ run }: { run: AgentRun }) {
  const now = useNow()
  const tail = run.logs.slice(-2)
  return (
    <Link
      href={`/runs/${run.id}`}
      className="grid grid-cols-[110px_1fr_auto] items-start gap-4 border-b px-4 py-3 transition-colors last:border-b-0 hover:bg-muted/40"
    >
      <div className="space-y-1.5">
        <AgentTag agent={run.agent} />
        <RunStatusBadge status={run.status} />
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm">
          {run.status === "running" ? run.current_step : run.error ?? run.summary}
        </p>
        <div className="mt-1.5 space-y-0.5 font-mono text-[11px] text-muted-foreground">
          {tail.map((log, i) => (
            <p key={i} className={cn("truncate", log.level === "error" && "text-destructive", log.level === "warn" && "text-warning")}>
              <span className="text-muted-foreground/50">{clock(log.ts)}</span> {log.message}
            </p>
          ))}
        </div>
      </div>
      <div className="text-right font-mono text-xs text-muted-foreground">
        <p>#{run.id}</p>
        <p className="mt-1.5">
          {run.started_at
            ? run.status === "running"
              ? duration(run.started_at, null, now)
              : timeAgo(run.finished_at ?? run.started_at, now)
            : "queued"}
        </p>
      </div>
    </Link>
  )
}

function MeterCard({ meter }: { meter: UsageMeter }) {
  const pct = meter.limit ? Math.min(100, (meter.used / meter.limit) * 100) : null
  const tone = pct === null ? "bg-info" : pct >= 80 ? "bg-destructive" : pct >= 60 ? "bg-warning" : "bg-brand"
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex items-center justify-between text-sm">
          {meter.label}
          {meter.errors > 0 && meter.calls === meter.errors ? (
            <span className="size-1.5 rounded-full bg-destructive" title="All calls failing" />
          ) : (
            <CheckCircle2Icon className="size-3.5 text-success" />
          )}
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
          <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct ?? 100}%`, opacity: pct === null ? 0.3 : 1 }} />
        </div>
        <p className="font-mono text-[10px] text-muted-foreground">
          {meter.errors} err · {meter.fallbacks} fallback
        </p>
        {meter.note && <p className="text-[11px] leading-4 text-muted-foreground">{meter.note}</p>}
      </CardContent>
    </Card>
  )
}
