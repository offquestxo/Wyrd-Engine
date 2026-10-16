"use client"

import { ActivityIcon, ClipboardListIcon, LayersIcon } from "lucide-react"
import useSWR from "swr"

import { AgentStatus } from "@/components/blocks/agent-status"
import { MeterBar } from "@/components/blocks/meter-bar"
import { PlanCard } from "@/components/blocks/plan-card"
import { RunCard } from "@/components/blocks/run-card"
import { SeriesChip, SeriesDot } from "@/components/blocks/series"
import { StatTile } from "@/components/blocks/stat-tile"
import { ThumbnailBlock } from "@/components/blocks/thumbnail-block"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { fetcher } from "@/lib/api"
import { SERIES_STYLES } from "@/lib/series"
import type { PlanRecord, RunRecord, Story, UsageReport } from "@/lib/types"

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {note && <p className="text-xs text-subtle-foreground">{note}</p>}
      </div>
      {children}
    </section>
  )
}

/** Labelled so nobody mistakes a state fixture for engine data. */
function Fixture({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-2 rounded-xl border border-dashed p-3">
      <span className="font-mono text-[10.5px] tracking-[0.8px] text-subtle-foreground">STATE FIXTURE · NOT ENGINE DATA</span>
      {children}
    </div>
  )
}

export function ComponentPreview() {
  const stories = useSWR<Story[]>("/api/stories?limit=500", fetcher)
  const usage = useSWR<UsageReport>("/api/usage", fetcher)
  const runs = useSWR<RunRecord[]>("/api/runs?limit=6", fetcher)
  const plans = useSWR<PlanRecord[]>("/api/plans?limit=5", fetcher)

  const bySeries = SERIES_STYLES.map((s) => stories.data?.find((x) => x.series === s.label)).filter(Boolean) as Story[]
  const noSeries = stories.data?.find((x) => !x.series)
  const counts = (status: string) => stories.data?.filter((x) => x.status === status).length

  return (
    <div className="bg-grid mx-auto max-w-6xl space-y-10 p-4 md:p-8">
      <header className="space-y-1">
        <p className="num text-xs text-subtle-foreground">DEV ONLY · /dev/components</p>
        <h1 className="text-[34px] font-semibold tracking-[-1px]">Shared components</h1>
        <p className="text-sm text-muted-foreground">Redesign stage 1, on live engine data. Dashed boxes are state fixtures.</p>
      </header>

      <Section title="Type" note="Geist (UI) · Geist Mono (numbers) · Bricolage Grotesque (creative headings + thumbnail figures only)">
        <div className="grid gap-4 rounded-xl border bg-card p-5 md:grid-cols-3">
          <div>
            <p className="text-[34px] font-semibold tracking-[-1px]">Mission control</p>
            <p className="text-sm text-muted-foreground">Data page title · Geist 600</p>
          </div>
          <div>
            <p className="font-display text-[34px] font-extrabold tracking-[-1px]">Stories</p>
            <p className="text-sm text-muted-foreground">Creative title · Bricolage 800</p>
          </div>
          <div>
            <p className="num text-[36px] font-semibold tracking-[-1px]">1,240</p>
            <p className="text-sm text-muted-foreground">Numbers · Geist Mono, tabular</p>
          </div>
        </div>
      </Section>

      <Section title="ThumbnailBlock" note="Real stories, one per series. Stories have no hook_figure yet (stage 4), so the company/title is the big text.">
        {stories.isLoading ? (
          <LoadingState rows={2} />
        ) : stories.error ? (
          <ErrorState error={stories.error as Error} onRetry={() => void stories.mutate()} />
        ) : bySeries.length === 0 ? (
          <EmptyState icon={LayersIcon} title="No stories yet" description="Run @scout to find some." />
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
            {[...bySeries, ...(noSeries ? [noSeries] : [])].map((s) => (
              <div key={s.id} className="space-y-2">
                <ThumbnailBlock series={s.series} fallback={s.company ?? s.title} />
                <div className="flex items-center gap-2 text-sm">
                  <span className="truncate font-medium">{s.company ?? s.title}</span>
                  <span className="num ml-auto font-semibold">{s.total_score ?? "—"}</span>
                </div>
              </div>
            ))}
          </div>
        )}
        <Fixture>
          <div className="grid gap-3 md:grid-cols-[repeat(3,minmax(0,1fr))_1.4fr]">
            <ThumbnailBlock series="Fraud Files" figure="3,400" caption="best salespeople, fired" fallback="Example" />
            <ThumbnailBlock series="Tech Graveyard" figure="$61,000" caption="of panned gold" verified fallback="Example" />
            <ThumbnailBlock series={null} fallback="A long company name with no figure" />
            <ThumbnailBlock series="Comebacks" figure="70M oz" caption="claimed, almost none real" size="lg" fallback="Example" />
          </div>
          <p className="text-xs text-subtle-foreground">&quot;?&quot; = unverified lead from source text · ✓ = confirmed by a dossier&apos;s Key Numbers</p>
        </Fixture>
      </Section>

      <Section title="SeriesChip / SeriesDot">
        <div className="flex flex-wrap gap-2">
          {SERIES_STYLES.map((s) => (
            <SeriesChip key={s.key} series={s.label} />
          ))}
          <SeriesChip series={null} />
        </div>
        <div className="flex flex-wrap gap-2">
          {SERIES_STYLES.map((s) => (
            <span key={s.key} className="inline-flex h-9 items-center rounded-full border bg-card-creative px-3.5">
              <SeriesChip series={s.label} variant="filter" />
            </span>
          ))}
        </div>
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <SeriesDot series="Fraud Files" /> table rows use the dot
        </p>
      </Section>

      <Section title="StatTile" note="Live counts from /api/stories.">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3.5">
          <StatTile label="Inbox" value={counts("Inbox")} loading={stories.isLoading} delta={`${stories.data?.length ?? 0} stories in total`} />
          <StatTile label="Shortlisted" value={counts("Shortlisted")} loading={stories.isLoading} />
          <StatTile label="Researching" value={counts("Researching")} loading={stories.isLoading} deltaTone="live" delta="live" />
          <StatTile label="Sparkline example" value={12} sparkline={[3, 5, 4, 8, 6, 9, 12]} delta="+4 this week (fixture)" deltaTone="success" />
        </div>
      </Section>

      <Section title="MeterBar" note="Today's usage from /api/usage.">
        <div className="grid gap-5 rounded-xl border bg-card p-[18px] md:grid-cols-2">
          {usage.isLoading && <LoadingState rows={3} />}
          {usage.data?.meters.map((m) => (
            <MeterBar
              key={m.provider}
              label={m.status === "disabled" ? `${m.label} (disabled)` : m.label}
              used={m.used}
              limit={m.status === "disabled" ? null : m.limit}
              unit={m.unit}
            />
          ))}
        </div>
        <Fixture>
          <div className="grid gap-5 md:grid-cols-3">
            <MeterBar label="Below 70 %" used={412} limit={14400} unit="req" />
            <MeterBar label="At 75 %" used={188} limit={250} unit="req" hint="router will prefer NVIDIA soon" />
            <MeterBar label="At 95 %" used={19} limit={20} unit="req" />
          </div>
        </Fixture>
      </Section>

      <Section title="AgentStatus">
        <Fixture>
          <div className="flex flex-wrap gap-6">
            <AgentStatus state="running" />
            <AgentStatus state="idle" />
            <AgentStatus state="failed" />
          </div>
        </Fixture>
      </Section>

      <Section title="RunCard" note="Latest runs from /api/runs. Running runs get the live card; finished ones collapse to one line.">
        {runs.isLoading && <LoadingState rows={3} />}
        {runs.data?.length === 0 && <EmptyState icon={ActivityIcon} title="No runs yet" description="Approve a plan to start one." />}
        <div className="space-y-3">
          {runs.data?.slice(0, 4).map((r) => (
            <RunCard key={r.id} run={r} />
          ))}
        </div>
      </Section>

      <Section title="PlanCard v2" note="Latest plans from /api/plans. Approve/Cancel act on the real plan. Focus a card and press ⌘⏎ to approve.">
        {plans.isLoading && <LoadingState rows={3} />}
        {plans.data?.length === 0 && <EmptyState icon={ClipboardListIcon} title="No plans yet" description="Ask the orchestrator in Chat." />}
        {plans.data?.[0] && (
          <div className="space-y-4">
            <PlanCard plan={plans.data[0]} variant="compact" onChange={() => void plans.mutate()} />
            <div className="surface-creative rounded-2xl p-4">
              <PlanCard plan={plans.data[0]} variant="creative" onChange={() => void plans.mutate()} />
            </div>
          </div>
        )}
      </Section>
    </div>
  )
}
