"use client"

import { ChevronRightIcon, FlameIcon, PlusIcon, SearchIcon } from "lucide-react"
import { Fragment, useMemo, useState } from "react"
import { toast } from "sonner"

import { PageHeader } from "@/components/common/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDemo } from "@/hooks/use-demo"
import { formatNumber, timeAgo } from "@/lib/format"
import { MOCK_OUTLIERS } from "@/lib/mock"
import { cn } from "@/lib/utils"

export function OutliersView() {
  const { data, isLoading, error, retry } = useDemo(MOCK_OUTLIERS, [])
  const [channel, setChannel] = useState("all")
  const [format, setFormat] = useState("all")
  const [expanded, setExpanded] = useState<number | null>(null)

  const channels = useMemo(() => [...new Set((data ?? []).map((v) => v.channel))], [data])
  const rows = useMemo(
    () =>
      (data ?? [])
        .filter((v) => (channel === "all" || v.channel === channel) && (format === "all" || (format === "shorts") === v.is_short))
        .sort((a, b) => b.outlier_score - a.outlier_score),
    [data, channel, format],
  )

  return (
    <div className="mx-auto max-w-7xl px-8 py-8">
      <PageHeader
        title="Outliers"
        description="Competitor videos that beat their channel's median views for their format."
        sample
      />
      <div className="mb-4 flex items-center gap-2">
        <Select value={channel} onValueChange={setChannel}>
          <SelectTrigger size="sm" className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All channels</SelectItem>
            {channels.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
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
        <ErrorState error={error} onRetry={retry} />
      ) : !data?.length ? (
        <EmptyState
          icon={FlameIcon}
          title="No outliers yet"
          description="Run @outlier to scan competitor channels (Company Man, Modern MBA, Magnates Media)."
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
                      <p className="truncate font-medium">{v.title}</p>
                      <p className="text-xs text-muted-foreground">{v.channel} · {timeAgo(v.published_at)}</p>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px]">{v.is_short ? "Short" : "Long"}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {formatNumber(v.views)}
                      <p className="text-[10px] text-muted-foreground">median {formatNumber(v.channel_median)}</p>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm text-brand">{v.outlier_score}×</TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground 2xl:table-cell">{v.analysis.hook_pattern}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="xs"
                        variant="outline"
                        onClick={(e) => {
                          e.stopPropagation()
                          toast.success("Sample story created", { description: "Real stories from outliers arrive in Phase 4." })
                        }}
                      >
                        <PlusIcon /> Create story
                      </Button>
                    </TableCell>
                  </TableRow>
                  {expanded === v.id && (
                    <TableRow className="bg-muted/20 hover:bg-muted/20">
                      <TableCell />
                      <TableCell colSpan={6} className="py-4">
                        <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
                          {[
                            ["Hook pattern", v.analysis.hook_pattern],
                            ["Topic", v.analysis.topic],
                            ["Company type", v.analysis.company_type],
                            ["Why it worked", v.analysis.why_it_worked],
                            ["wyrd.exe angle", v.analysis.wyrd_angle],
                          ].map(([k, val]) => (
                            <div key={k}>
                              <dt className="text-[11px] tracking-wide text-muted-foreground uppercase">{k}</dt>
                              <dd className="mt-0.5 whitespace-normal">{val}</dd>
                            </div>
                          ))}
                        </dl>
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
