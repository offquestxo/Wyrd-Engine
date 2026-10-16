"use client"

import { ArrowRightIcon, ExternalLinkIcon, FlameIcon, Loader2Icon, PlusIcon, SearchIcon } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { UnverifiedBadge } from "@/components/common/badges"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { OutlierLauncher } from "@/components/outliers/outlier-launcher"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useChannels, useOutliers, useUsage } from "@/hooks/use-live"
import { api } from "@/lib/api"
import { formatNumber, timeAgo } from "@/lib/format"
import type { OutlierVideo } from "@/lib/types"
import { cn } from "@/lib/utils"

type Format = "both" | "long" | "shorts"

function SummaryTile({ label, children, loading }: { label: string; children: React.ReactNode; loading?: boolean }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border bg-card px-4 py-3.5">
      <span className="text-[12.5px] text-muted-foreground">{label}</span>
      {loading ? <Skeleton className="h-7 w-14" /> : <span className="num text-[26px] leading-tight font-semibold">{children}</span>}
    </div>
  )
}

export function OutliersView() {
  const router = useRouter()
  const { data, isLoading, error, mutate } = useOutliers()
  const channels = useChannels()
  const usage = useUsage()
  const [channel, setChannel] = useState("all")
  const [format, setFormat] = useState<Format>("both")
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [creating, setCreating] = useState<string | null>(null)

  const rows = useMemo(
    () =>
      (data ?? []).filter(
        (v) =>
          (channel === "all" || v.channel_handle === channel) &&
          (format === "both" || (format === "shorts") === v.is_short),
      ),
    [data, channel, format],
  )
  const selected = rows.find((v) => v.id === selectedId) ?? rows[0] ?? null
  const max = Math.max(1, ...rows.map((v) => v.outlier_score ?? 0))
  const scanned = (channels.data ?? []).reduce((n, c) => n + c.videos, 0)
  const youtube = usage.data?.meters.find((m) => m.provider === "youtube")
  const lastScan = (channels.data ?? []).reduce<string | null>((m, c) => (c.last_scanned_at && (!m || c.last_scanned_at > m) ? c.last_scanned_at : m), null)

  const createStory = async (v: OutlierVideo) => {
    setCreating(v.video_id)
    try {
      const res = await api<{ story_id: number; created: boolean }>(`/api/outliers/${v.video_id}/story`, { method: "POST" })
      toast.success(res.created ? "Story created in Inbox" : "A story for this video already exists", {
        action: { label: "Open", onClick: () => router.push(`/stories?story=${res.story_id}`) },
      })
      await mutate()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setCreating(null)
    }
  }

  return (
    <div className="bg-grid min-h-full">
      <div className="mx-auto flex max-w-[1320px] flex-col gap-5 px-4 py-6 md:px-8 md:py-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-1.5">
            <span className="num text-[11.5px] tracking-[1.4px] text-subtle-foreground">
              {lastScan ? `LAST SCAN ${timeAgo(lastScan).toUpperCase()}` : "NOT SCANNED YET"}
            </span>
            <h1 className="text-[34px] leading-tight font-semibold tracking-[-0.8px]">Outliers</h1>
            <p className="max-w-2xl text-[14.5px] text-muted-foreground">
              Competitor videos that beat their channel&apos;s median views. Shorts and long-form are compared separately.
            </p>
          </div>
          <OutlierLauncher />
        </header>

        <section aria-label="Scan summary" className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <SummaryTile label="Videos scanned" loading={channels.isLoading}>
            {scanned.toLocaleString("en-US")}
          </SummaryTile>
          <SummaryTile label="Flagged outliers" loading={isLoading}>
            <span className="text-live-text">{data?.length ?? 0}</span>
          </SummaryTile>
          <SummaryTile label="Biggest outlier" loading={isLoading}>
            {data?.length ? `${Math.max(...data.map((v) => v.outlier_score ?? 0)).toFixed(1)}×` : "—"}
          </SummaryTile>
          <SummaryTile label="YouTube units today" loading={usage.isLoading}>
            {(youtube?.used ?? 0).toLocaleString("en-US")}{" "}
            <span className="text-[13px] font-normal text-subtle-foreground">of {(youtube?.limit ?? 10000).toLocaleString("en-US")}</span>
          </SummaryTile>
        </section>

        <div className="flex flex-wrap items-center gap-2.5">
          <div role="group" aria-label="Channel" className="flex flex-wrap gap-1.5">
            {[["all", "All channels"] as const, ...(channels.data ?? []).map((c) => [c.handle, c.name ?? c.handle] as const)].map(([handle, name]) => (
              <button
                key={handle}
                type="button"
                aria-pressed={channel === handle}
                onClick={() => setChannel(handle)}
                className={cn(
                  "h-9 rounded-full px-3.5 text-[13px] transition-colors",
                  channel === handle ? "bg-foreground font-semibold text-background" : "border border-white/8 bg-[#11131b] text-[#d5d8e2] hover:border-white/20",
                )}
              >
                {name}
              </button>
            ))}
          </div>
          <div role="group" aria-label="Format" className="ml-auto flex rounded-[10px] border border-white/8 bg-[#11131b] p-[3px]">
            {(["both", "long", "shorts"] as const).map((f) => (
              <button
                key={f}
                type="button"
                aria-pressed={format === f}
                onClick={() => setFormat(f)}
                className={cn("h-8 rounded-[7px] px-3 text-[13px]", format === f ? "bg-[#1f2230] text-foreground" : "text-muted-foreground hover:text-foreground")}
              >
                {f === "both" ? "Both" : f === "long" ? "Long-form" : "Shorts"}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <LoadingState rows={6} />
        ) : error ? (
          <ErrorState error={error as Error} onRetry={() => void mutate()} />
        ) : !data?.length ? (
          <EmptyState
            icon={FlameIcon}
            title="No outliers yet"
            description="Run @outlier to scan the competitor channels in Settings → Channels."
            action={<OutlierLauncher />}
          />
        ) : rows.length === 0 ? (
          <EmptyState icon={SearchIcon} title="No videos match these filters" />
        ) : (
          <div className="flex flex-wrap items-start gap-4">
            <section aria-label="Flagged videos" className="min-w-0 flex-[2_1_440px] overflow-x-auto rounded-xl border bg-card">
              <div className="min-w-[460px]">
                <div className="grid grid-cols-[minmax(0,2.6fr)_0.6fr_1.3fr] gap-3 border-b border-white/6 px-[18px] py-3 font-mono text-xs tracking-[0.5px] text-subtle-foreground">
                  <span>VIDEO</span>
                  <span className="text-right">VIEWS</span>
                  <span>OUTLIER</span>
                </div>
                {rows.map((v) => {
                  const active = selected?.id === v.id
                  return (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => setSelectedId(v.id)}
                      aria-pressed={active}
                      className={cn(
                        "grid w-full grid-cols-[minmax(0,2.6fr)_0.6fr_1.3fr] items-center gap-3 border-b border-white/5 px-[18px] py-3 text-left transition-colors last:border-b-0 hover:bg-white/3",
                        active && "bg-brand-muted hover:bg-brand-muted",
                      )}
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        {v.thumbnail_url ? (
                          // eslint-disable-next-line @next/next/no-img-element -- remote YouTube thumbnail, no optimisation needed
                          <img src={v.thumbnail_url} alt="" className="h-9 w-16 shrink-0 rounded-md border border-white/8 object-cover" loading="lazy" />
                        ) : (
                          <span className="h-9 w-16 shrink-0 rounded-md border border-white/8 bg-[#1b1530]" />
                        )}
                        <span className="flex min-w-0 flex-col">
                          <span className="truncate text-sm">{v.title}</span>
                          <span className="truncate text-[12.5px] text-[#b4b8c6]">
                            {v.channel_name ?? v.channel_handle} · {v.is_short ? "Short" : "Long-form"}
                          </span>
                        </span>
                      </span>
                      <span className="num text-right text-[13px]">{formatNumber(v.views ?? 0)}</span>
                      <span className="flex items-center gap-2.5">
                        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                          <span
                            className="block h-full bg-live shadow-[0_0_8px_rgb(34_211_238/0.6)] motion-reduce:shadow-none"
                            // Log scale: one 30× video shouldn't flatten every 4× bar.
                            style={{ width: `${Math.max(4, (Math.log(Math.max(v.outlier_score ?? 1, 1)) / Math.log(Math.max(max, 2))) * 100)}%` }}
                          />
                        </span>
                        <span className="num w-12 text-right text-[13.5px] font-semibold text-live-text">{v.outlier_score?.toFixed(1)}×</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </section>

            {selected && (
              <OutlierDetail video={selected} creating={creating === selected.video_id} onCreate={() => void createStory(selected)} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function OutlierDetail({ video: v, creating, onCreate }: { video: OutlierVideo; creating: boolean; onCreate: () => void }) {
  return (
    <aside
      aria-label="Selected outlier"
      className="flex min-w-0 flex-[1_1_300px] flex-col gap-4 rounded-xl border border-transparent bg-card p-[18px] glow-brand"
    >
      {v.thumbnail_url ? (
        // eslint-disable-next-line @next/next/no-img-element -- remote YouTube thumbnail
        <img src={v.thumbnail_url} alt={`Thumbnail of “${v.title}”`} className="aspect-video w-full rounded-[10px] border border-white/8 object-cover" />
      ) : (
        <div className="flex aspect-video items-center justify-center rounded-[10px] border border-white/8 bg-[#1b1530] text-[13px] text-subtle-foreground">
          No thumbnail
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        <span className="num text-[11.5px] tracking-[1px] text-live-text">
          {v.outlier_score?.toFixed(1)}× CHANNEL MEDIAN · {v.is_short ? "SHORT" : "LONG-FORM"}
        </span>
        <h2 className="text-[19px] leading-snug font-semibold">{v.title}</h2>
        <span className="text-[13px] text-subtle-foreground">
          {v.channel_name ?? v.channel_handle} · <span className="num">{formatNumber(v.views ?? 0)}</span> views · median{" "}
          <span className="num">{formatNumber(Math.round(v.channel_median ?? 0))}</span>
          {v.published_at && ` · ${timeAgo(v.published_at)}`}
        </span>
      </div>
      <div className="flex flex-col gap-3 border-t border-white/6 pt-3.5">
        <span className="flex items-center gap-2 font-mono text-xs tracking-[0.6px] text-subtle-foreground">
          GEMINI ANALYSIS <UnverifiedBadge compact />
        </span>
        {v.analysis ? (
          [
            ["Why it worked", v.analysis.why_it_worked, false],
            ["Hook pattern", v.analysis.hook_pattern, true],
            ["Topic", v.analysis.topic, false],
            ["wyrd.exe angle", v.analysis.wyrd_angle, false],
          ].map(([label, value, mono]) => (
            <div key={label as string} className="flex flex-col gap-1">
              <span className="text-[12.5px] text-muted-foreground">{label}</span>
              <span className={cn("text-sm leading-normal", mono && "font-mono text-[13px] text-[#ede9fe]")}>{value}</span>
            </div>
          ))
        ) : (
          <p className="text-sm text-muted-foreground">Not analysed yet. The next @outlier run analyses it.</p>
        )}
      </div>
      <div className="mt-1 flex flex-col gap-2">
        {v.story_id ? (
          <Button asChild className="h-11 bg-brand text-brand-foreground hover:bg-brand/90">
            <Link href={`/stories?story=${v.story_id}`}>
              Open its story <ArrowRightIcon />
            </Link>
          </Button>
        ) : (
          <Button className="h-11 bg-brand text-brand-foreground hover:bg-brand/90" disabled={creating} onClick={onCreate}>
            {creating ? <Loader2Icon className="animate-spin" /> : <PlusIcon />} Create story from this
          </Button>
        )}
        <Button asChild variant="secondary" className="h-11">
          <a href={v.url} target="_blank" rel="noreferrer">
            Open on YouTube <ExternalLinkIcon />
          </a>
        </Button>
      </div>
    </aside>
  )
}
