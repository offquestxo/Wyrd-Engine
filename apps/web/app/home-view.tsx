"use client"

import { ActivityIcon, ArrowRightIcon, MessageSquareIcon, PlusIcon, SparklesIcon } from "lucide-react"
import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { MeterBar } from "@/components/blocks/meter-bar"
import { PlanCard } from "@/components/blocks/plan-card"
import { RunCard } from "@/components/blocks/run-card"
import { SeriesChip } from "@/components/blocks/series"
import { StatTile } from "@/components/blocks/stat-tile"
import { UnverifiedBadge } from "@/components/common/badges"
import { Kbd } from "@/components/common/kbd"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { useProposePlan } from "@/components/plans/propose-provider"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useEngineEvent } from "@/hooks/use-events"
import { useChannels, useOutliers, usePlans, useRuns, useStories, useUsage } from "@/hooks/use-live"
import { useMounted } from "@/hooks/use-local-state"
import { useNow } from "@/hooks/use-now"
import { api, fetcher } from "@/lib/api"
import { timeAgo } from "@/lib/format"
import { STORY_STATUSES, type DossierSummary, type ProviderMeter, type Story } from "@/lib/types"
import { cn } from "@/lib/utils"

const DAY = 86_400_000
const FUEL_ORDER = ["claude", "groq", "gemini", "nvidia", "openrouter", "youtube", "mistral"]

/** "FRI · OCT 16 · 11:06 EDT" in the owner's local time. */
function headerClock(now: number): string {
  const d = new Date(now)
  const weekday = d.toLocaleDateString("en-US", { weekday: "short" }).toUpperCase()
  const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric" }).toUpperCase()
  const time = d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZoneName: "short" })
  return `${weekday} · ${date} · ${time}`
}

export const OPEN_PALETTE_EVENT = "wyrd:open-palette"
const openPalette = () => window.dispatchEvent(new Event(OPEN_PALETTE_EVENT))

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

export function HomeView() {
  const now = useNow(30_000)
  const mounted = useMounted()
  const stories = useStories()
  const runs = useRuns("limit=12")
  const usage = useUsage()
  const pending = usePlans("pending")
  const outliers = useOutliers()
  const channels = useChannels()
  const dossiers = useSWR<DossierSummary[]>("/api/dossiers", fetcher)
  useEngineEvent(["dossier.saved"], () => void dossiers.mutate())

  // "N" = New run: opens the palette (owned by the shell). Ignored while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (e.key !== "n" || e.metaKey || e.ctrlKey || e.altKey) return
      if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return
      e.preventDefault()
      openPalette()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const list = useMemo(() => stories.data ?? [], [stories.data])
  const byStatus = (s: string) => list.filter((x) => x.status === s)
  const since = (iso: string, ms: number) => now - new Date(iso).getTime() < ms
  const newStories = list.filter((s) => since(s.created_at, DAY)).length
  const active = (runs.data ?? []).filter((r) => r.status === "running" || r.status === "queued")
  const researched = new Set((dossiers.data ?? []).map((d) => d.story_id))
  const weekOutliers = (outliers.data ?? []).filter((v) => v.scanned_at && since(v.scanned_at, 7 * DAY))
  const topOutlier = weekOutliers.reduce((m, v) => Math.max(m, v.outlier_score ?? 0), 0)
  const latestDossier = [...(dossiers.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
  const unresolved = (dossiers.data ?? []).filter((d) => d.unresolved_flags > 0).length

  // Stories created per day over the last 7 days (oldest → today), for the Inbox sparkline.
  const perDay = useMemo(() => {
    const days = Array.from({ length: 7 }, () => 0)
    for (const s of list) {
      const age = Math.floor((now - new Date(s.created_at).getTime()) / DAY)
      if (age >= 0 && age < 7) days[6 - age] += 1
    }
    return days
  }, [list, now])

  const summary = [
    plural(active.length, "agent") + " running",
    pending.data?.length ? `${plural(pending.data.length, "plan")} waiting for you` : "no plans waiting",
    `${plural(newStories, "new story", "new stories")} since yesterday`,
  ].join(" · ")

  return (
    <div className="bg-grid min-h-full">
      <div className="mx-auto flex max-w-[1240px] flex-col gap-7 px-4 py-6 md:px-8 md:py-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-1.5">
            {/* Client-only: the server's render time would never match. */}
            <span className="num h-4 text-[11.5px] tracking-[1.4px] text-subtle-foreground">{mounted ? headerClock(now) : ""}</span>
            <h1 className="text-[34px] leading-tight font-semibold tracking-[-0.8px]">Mission control</h1>
            {stories.isLoading || runs.isLoading ? (
              <Skeleton className="h-5 w-80" />
            ) : (
              <p className="text-[14.5px] text-muted-foreground">{summary}</p>
            )}
          </div>
          <div className="flex flex-wrap gap-2.5">
            <Button asChild variant="outline" className="h-11 gap-2 bg-[#11131b] px-4">
              <Link href="/chat">
                <MessageSquareIcon /> Ask the orchestrator
              </Link>
            </Button>
            <Button
              className="h-11 gap-2.5 bg-brand px-4 text-brand-foreground shadow-[0_0_0_1px_rgb(196_181_253/0.4),0_8px_28px_rgb(124_58_237/0.45)] hover:bg-brand/90"
              onClick={openPalette}
            >
              <PlusIcon /> New run <Kbd className="border-0 bg-white/18 text-[11px] text-white">N</Kbd>
            </Button>
          </div>
        </header>

        {pending.data && pending.data.length > 0 && (
          <section aria-label="Waiting for approval" className="flex flex-col gap-3">
            {pending.data.slice(0, 2).map((plan) => (
              <PlanCard key={plan.id} plan={plan} variant="compact" onChange={() => void pending.mutate()} />
            ))}
            {pending.data.length > 2 && (
              <Link href="/chat" className="text-[13px] text-brand-soft hover:underline">
                +{pending.data.length - 2} more waiting in Chat →
              </Link>
            )}
          </section>
        )}

        <section aria-label="Pipeline at a glance" className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3.5">
          <StatTile
            label="Inbox"
            value={byStatus("Inbox").length}
            loading={stories.isLoading}
            sparkline={perDay.some(Boolean) ? perDay : undefined}
            delta={newStories > 0 ? `+${newStories} since yesterday` : "nothing new since yesterday"}
            deltaTone={newStories > 0 ? "success" : "neutral"}
          />
          <StatTile
            label="Shortlisted"
            value={byStatus("Shortlisted").length}
            loading={stories.isLoading}
            delta={`${byStatus("Shortlisted").filter((s) => !researched.has(s.id)).length} ready to research`}
          />
          <StatTile
            label="Dossiers ready"
            value={dossiers.data?.length}
            loading={dossiers.isLoading}
            delta={
              unresolved > 0
                ? `${plural(unresolved, "dossier")} with unresolved flags`
                : latestDossier
                  ? `latest: ${latestDossier.story_title.slice(0, 28)} · ${timeAgo(latestDossier.created_at, now)}`
                  : "none yet"
            }
            deltaTone={unresolved > 0 ? "warning" : "neutral"}
          />
          <StatTile
            label="Outliers this week"
            value={weekOutliers.length}
            loading={outliers.isLoading}
            aside={topOutlier > 0 ? <span className="num text-xs text-live-text">top {topOutlier.toFixed(1)}×</span> : undefined}
            delta={`across ${plural(channels.data?.length ?? 0, "channel")}`}
          />
        </section>

        <div className="flex flex-wrap items-start gap-5">
          <section aria-label="Live agents" className="flex min-w-0 flex-[2_1_520px] flex-col gap-3">
            <h2 className="text-[15px] font-semibold">Live agents</h2>
            {runs.isLoading ? (
              <LoadingState rows={3} />
            ) : runs.error ? (
              <ErrorState error={runs.error as Error} onRetry={() => void runs.mutate()} />
            ) : !runs.data?.length ? (
              <EmptyState
                icon={ActivityIcon}
                title="No runs yet"
                description="Start an agent and watch it work here."
                action={<Button onClick={openPalette}>New run</Button>}
              />
            ) : (
              <div className="flex flex-col gap-3">
                {active.length === 0 && (
                  <p className="rounded-xl border border-dashed px-4 py-3 text-sm text-subtle-foreground">
                    No agents running right now. Recent runs:
                  </p>
                )}
                {[...active, ...runs.data.filter((r) => !active.includes(r))].slice(0, Math.max(4, active.length)).map((run) => (
                  <RunCard key={run.id} run={run} />
                ))}
              </div>
            )}
          </section>

          <FuelToday meters={usage.data?.meters} timezone={usage.data?.timezone} loading={usage.isLoading} error={usage.error as Error | undefined} onRetry={() => void usage.mutate()} />
        </div>

        <Pipeline stories={list} loading={stories.isLoading} />

        <TopPicks stories={list} loading={stories.isLoading} researched={researched} onChange={() => void stories.mutate()} />
      </div>
    </div>
  )
}

function FuelToday({
  meters,
  timezone,
  loading,
  error,
  onRetry,
}: {
  meters?: ProviderMeter[]
  timezone?: string
  loading: boolean
  error?: Error
  onRetry: () => void
}) {
  const sorted = [...(meters ?? [])].sort((a, b) => FUEL_ORDER.indexOf(a.provider) - FUEL_ORDER.indexOf(b.provider))
  const llm = sorted.filter((m) => m.provider !== "claude" && m.provider !== "youtube")
  const requests = llm.reduce((n, m) => n + m.requests, 0)
  const errors = llm.reduce((n, m) => n + m.errors, 0)
  const fallbacks = llm.reduce((n, m) => n + m.fallbacks, 0)
  return (
    <section aria-label="Quota today" className="flex min-w-0 flex-[1_1_300px] flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-[15px] font-semibold">Fuel today</h2>
        {timezone && <span className="num text-[11.5px] text-subtle-foreground">resets midnight {timezone.split("/").pop()?.replace("_", " ")}</span>}
      </div>
      <div className="flex flex-col gap-[18px] rounded-xl border bg-card p-[18px]">
        {loading ? (
          <LoadingState rows={5} />
        ) : error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : (
          <>
            {sorted.map((m) => {
              if (m.status === "disabled")
                return (
                  <div key={m.provider} className="flex items-center justify-between text-[13.5px] text-subtle-foreground">
                    <span>{m.label}</span>
                    <span className="text-xs">disabled</span>
                  </div>
                )
              if (m.provider === "claude" && m.claude)
                return (
                  <MeterBar
                    key={m.provider}
                    label="Claude"
                    used={m.claude.chat_turns + m.claude.agent_runs}
                    limit={m.claude.soft_cap}
                    unit="runs"
                    hint={m.claude.rate_limit?.status && m.claude.rate_limit.status !== "allowed" ? `Claude Code reports: ${m.claude.rate_limit.status}` : undefined}
                  />
                )
              return (
                <MeterBar
                  key={m.provider}
                  label={m.label}
                  used={m.used}
                  limit={m.limit}
                  unit={m.unit === "requests" ? "req" : m.unit}
                  hint={m.status === "missing" ? "no key set" : m.status === "failing" ? "key failing: see Settings" : undefined}
                />
              )
            })}
            <div className="grid grid-cols-2 gap-2.5 border-t pt-3.5">
              <div className="flex flex-col gap-1">
                <span className="text-xs text-subtle-foreground">Fallbacks</span>
                <span className="num text-[15px]">{fallbacks}</span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-xs text-subtle-foreground">Error rate</span>
                <span className="num text-[15px]">{requests ? `${((errors / requests) * 100).toFixed(1)}%` : "—"}</span>
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  )
}

function Pipeline({ stories, loading }: { stories: Story[]; loading: boolean }) {
  const statuses = STORY_STATUSES.filter((s) => s !== "Archived")
  return (
    <section aria-label="Story pipeline" className="flex flex-col gap-3">
      <h2 className="text-[15px] font-semibold">Pipeline</h2>
      <div className="overflow-x-auto rounded-xl border bg-card">
        <div className="grid min-w-[880px] grid-cols-8">
          {statuses.map((status, i) => {
            const n = stories.filter((s) => s.status === status).length
            const live = status === "Researching" && n > 0
            return (
              <Link
                key={status}
                href={`/stories?status=${encodeURIComponent(status)}`}
                className={cn("flex flex-col gap-1.5 px-4 py-3.5 transition-colors hover:bg-white/3", i < statuses.length - 1 && "border-r border-white/6", live && "bg-live/8")}
              >
                <span className={cn("text-xs", live ? "text-live-text" : "text-muted-foreground")}>{status}</span>
                {loading ? (
                  <Skeleton className="h-6 w-8" />
                ) : (
                  <span className={cn("num text-[22px] font-semibold", status === "Published" && n > 0 && "text-success-text")}>{n}</span>
                )}
              </Link>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function TopPicks({
  stories,
  loading,
  researched,
  onChange,
}: {
  stories: Story[]
  loading: boolean
  researched: Set<number>
  onChange: () => void
}) {
  const propose = useProposePlan()
  const [busy, setBusy] = useState<number | null>(null)
  const picks = stories
    .filter((s) => s.status === "Inbox")
    .sort((a, b) => (b.total_score ?? 0) - (a.total_score ?? 0))
    .slice(0, 3)

  const shortlist = async (story: Story) => {
    setBusy(story.id)
    try {
      await api(`/api/stories/${story.id}`, { method: "PATCH", body: JSON.stringify({ status: "Shortlisted" }) })
      toast.success(`Shortlisted “${story.company ?? story.title}”`)
      onChange()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <section aria-label="Top picks" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-[15px] font-semibold">Top picks from @scout</h2>
        <Link href="/stories" className="text-[13px] text-brand-soft hover:underline">
          Open Stories →
        </Link>
      </div>
      {loading ? (
        <LoadingState rows={2} />
      ) : picks.length === 0 ? (
        <EmptyState icon={SparklesIcon} title="Inbox is empty" description="Run @scout to find new story leads." />
      ) : (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-3.5">
          {picks.map((story) => (
            <article key={story.id} className="flex flex-col gap-3 rounded-xl border bg-card p-[18px]">
              <div className="flex items-center justify-between gap-2">
                <SeriesChip series={story.series} />
                <span className="num text-xl font-semibold text-brand-soft">{story.total_score?.toFixed(1) ?? "—"}</span>
              </div>
              <h3 className="line-clamp-2 text-[17px] font-semibold">
                <Link href={`/stories?story=${story.id}`} className="hover:underline">
                  {story.company ?? story.title}
                </Link>
              </h3>
              {story.hook && (
                <p className="line-clamp-3 text-sm leading-normal text-muted-foreground">
                  <UnverifiedBadge compact /> {story.hook}
                </p>
              )}
              <div className="mt-auto flex gap-2">
                <Button variant="secondary" className="h-10 flex-1" disabled={busy === story.id} onClick={() => void shortlist(story)}>
                  Shortlist
                </Button>
                <Button
                  variant="outline"
                  className="h-10 flex-1 border-brand-soft/40 bg-brand/16 text-[#ede9fe] hover:bg-brand/25"
                  disabled={researched.has(story.id)}
                  title={researched.has(story.id) ? "Already has a dossier" : undefined}
                  onClick={() => void propose("researcher", { story_id: story.id, depth: "standard" }, `Research “${story.title}” (standard depth)`)}
                >
                  Research this <ArrowRightIcon />
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
