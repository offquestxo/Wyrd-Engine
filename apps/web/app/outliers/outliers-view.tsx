"use client"

import { ArrowRightIcon, ChevronRightIcon, ExternalLinkIcon, FlameIcon, Loader2Icon, PlusIcon, SearchIcon } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Fragment, useMemo, useState } from "react"
import { toast } from "sonner"

import { UnverifiedBadge } from "@/components/common/badges"
import { PageHeader } from "@/components/common/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { OutlierLauncher } from "@/components/outliers/outlier-launcher"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useOutliers } from "@/hooks/use-live"
import { api } from "@/lib/api"
import { formatNumber, timeAgo } from "@/lib/format"
import type { OutlierVideo } from "@/lib/types"
import { cn } from "@/lib/utils"

export function OutliersView() {
  const router = useRouter()
  const { data, isLoading, error, mutate } = useOutliers()
  const [channel, setChannel] = useState("all")
  const [format, setFormat] = useState("all")
  const [expanded, setExpanded] = useState<number | null>(null)
  const [creating, setCreating] = useState<string | null>(null)

  const channels = useMemo(
    () => [...new Map((data ?? []).map((v) => [v.channel_handle ?? "", v.channel_name ?? v.channel_handle ?? ""])).entries()],
    [data],
  )
  const rows = useMemo(
    () =>
      (data ?? []).filter(
        (v) => (channel === "all" || v.channel_handle === channel) && (format === "all" || (format === "shorts") === v.is_short),
      ),
    [data, channel, format],
  )

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
    <div className="mx-auto max-w-7xl px-8 py-8">
      <PageHeader
        title="Outliers"
        description="Competitor videos that beat their channel's median views for their format (Shorts and long-form are compared separately)."
        actions={<OutlierLauncher />}
      />
      <div className="mb-4 flex items-center gap-2">
        <Select value={channel} onValueChange={setChannel}>
          <SelectTrigger size="sm" className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All channels</SelectItem>
            {channels.map(([handle, name]) => <SelectItem key={handle} value={handle}>{name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={format} onValueChange={setFormat}>
          <SelectTrigger size="sm" className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Shorts + long-form</SelectItem>
            <SelectItem value="shorts">Shorts</SelectItem>
            <SelectItem value="long">Long-form</SelectItem>
          </SelectContent>
        </Select>
        <span className="ml-auto font-mono text-xs text-muted-foreground">{rows.length} videos</span>
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
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-8" />
                <TableHead>Video</TableHead>
                <TableHead>Format</TableHead>
                <TableHead className="text-right">Views</TableHead>
                <TableHead className="text-right">Outlier</TableHead>
                <TableHead className="hidden 2xl:table-cell">Hook pattern</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((v) => (
                <Fragment key={v.id}>
                  <TableRow className="cursor-pointer" onClick={() => setExpanded(expanded === v.id ? null : v.id)}>
                    <TableCell>
                      <ChevronRightIcon className={cn("size-3.5 text-muted-foreground transition-transform", expanded === v.id && "rotate-90")} />
                    </TableCell>
                    <TableCell className="max-w-sm">
                      <div className="flex items-center gap-3">
                        {v.thumbnail_url && (
                          // eslint-disable-next-line @next/next/no-img-element -- remote YouTube thumbnail, no optimisation needed
                          <img src={v.thumbnail_url} alt="" className="h-9 w-16 shrink-0 rounded object-cover" loading="lazy" />
                        )}
                        <div className="min-w-0">
                          <p className="truncate font-medium">{v.title}</p>
                          <p className="text-xs text-muted-foreground">
                            {v.channel_name} · {v.published_at ? timeAgo(v.published_at) : "—"}
                          </p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px]">{v.is_short ? "Short" : "Long"}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {formatNumber(v.views ?? 0)}
                      <p className="text-[10px] text-muted-foreground">median {formatNumber(Math.round(v.channel_median ?? 0))}</p>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm text-brand">{v.outlier_score}×</TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground 2xl:table-cell">
                      {v.analysis?.hook_pattern ?? <span className="italic">not analysed yet</span>}
                    </TableCell>
                    <TableCell className="text-right">
                      {v.story_id ? (
                        <Button size="xs" variant="ghost" asChild onClick={(e) => e.stopPropagation()}>
                          <Link href={`/stories?story=${v.story_id}`}>Story <ArrowRightIcon /></Link>
                        </Button>
                      ) : (
                        <Button
                          size="xs"
                          variant="outline"
                          disabled={creating === v.video_id}
                          onClick={(e) => {
                            e.stopPropagation()
                            void createStory(v)
                          }}
                        >
                          {creating === v.video_id ? <Loader2Icon className="animate-spin" /> : <PlusIcon />} Create story
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                  {expanded === v.id && (
                    <TableRow className="bg-muted/20 hover:bg-muted/20">
                      <TableCell />
                      <TableCell colSpan={6} className="py-4 whitespace-normal">
                        {v.analysis ? (
                          <>
                            <div className="mb-3 flex items-center gap-2">
                              <p className="text-[11px] tracking-wide text-muted-foreground uppercase">Analysis</p>
                              <UnverifiedBadge compact />
                            </div>
                            <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
                              {[
                                ["Topic", v.analysis.topic],
                                ["Company type", v.analysis.company_type],
                                ["Hook pattern", v.analysis.hook_pattern],
                                ["Why it worked", v.analysis.why_it_worked],
                                ["wyrd.exe angle", v.analysis.wyrd_angle],
                              ].map(([k, val]) => (
                                <div key={k}>
                                  <dt className="text-[11px] tracking-wide text-muted-foreground uppercase">{k}</dt>
                                  <dd className="mt-0.5">{val}</dd>
                                </div>
                              ))}
                            </dl>
                          </>
                        ) : (
                          <p className="text-sm text-muted-foreground">Not analysed yet. The next @outlier run analyses it.</p>
                        )}
                        <a href={v.url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs text-brand hover:underline">
                          Watch on YouTube <ExternalLinkIcon className="size-3" />
                        </a>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
