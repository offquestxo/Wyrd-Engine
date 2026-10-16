"use client"

import { ArrowDownIcon, ArrowUpIcon, KanbanIcon, LayersIcon, SearchIcon, TableIcon } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { ScoreBar, StoryStatusBadge, UnverifiedBadge } from "@/components/common/badges"
import { SeriesChip, SeriesDot } from "@/components/blocks/series"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { ScoutLauncher } from "@/components/stories/scout-launcher"
import { StoriesBoard } from "@/components/stories/stories-board"
import { StoryDrawer } from "@/components/stories/story-drawer"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useStories } from "@/hooks/use-live"
import { useLocalState } from "@/hooks/use-local-state"
import { api } from "@/lib/api"
import { timeAgo } from "@/lib/format"
import { SERIES_STYLES } from "@/lib/series"
import { STORY_STATUSES, type Story, type StoryStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

type SortKey = "title" | "status" | "score" | "gap" | "updated"
const ALL = "all"

export function StoriesView() {
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()
  const { data, isLoading, error, mutate } = useStories()
  const stories = useMemo(() => data ?? [], [data])
  const [view, setView] = useLocalState<"table" | "board">("wyrd.storiesView", "board")
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState<string>(() => params.get("status") ?? ALL)
  const [series, setSeries] = useState<string>(ALL)
  const [format, setFormat] = useState<string>(ALL)
  const [minScore, setMinScore] = useState<string>(ALL)
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "score", desc: true })

  const openId = Number(params.get("story")) || null
  const setOpen = (story: Story | null) => {
    const next = new URLSearchParams(params)
    if (story) next.set("story", String(story.id))
    else next.delete("story")
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false })
  }

  const move = async (story: Story, to: StoryStatus) => {
    // Optimistic: show the move at once, then confirm with the server.
    await mutate(stories.map((s) => (s.id === story.id ? { ...s, status: to } : s)), { revalidate: false })
    try {
      await api<Story>(`/api/stories/${story.id}`, { method: "PATCH", body: JSON.stringify({ status: to }) })
      toast.success(`${story.title} → ${to}`)
    } catch (e) {
      toast.error((e as Error).message)
    }
    await mutate()
  }

  const filtered = useMemo(() => {
    const q = query.toLowerCase()
    const rows = stories.filter(
      (s) =>
        (status === ALL || s.status === status) &&
        (series === ALL || s.series === series) &&
        (format === ALL || s.format === format) &&
        (minScore === ALL || (s.total_score ?? 0) >= Number(minScore)) &&
        (!q || `${s.title} ${s.company ?? ""} ${s.hook ?? ""}`.toLowerCase().includes(q)),
    )
    const value = (s: Story): string | number => {
      switch (sort.key) {
        case "title":
          return s.title.toLowerCase()
        case "status":
          return STORY_STATUSES.indexOf(s.status)
        case "score":
          return s.total_score ?? -1
        case "gap":
          return s.gap_score ?? -1
        case "updated":
          return s.updated_at
      }
    }
    return [...rows].sort((a, b) => {
      const [x, y] = [value(a), value(b)]
      const cmp = x < y ? -1 : x > y ? 1 : 0
      return sort.desc ? -cmp : cmp
    })
  }, [stories, query, status, series, format, minScore, sort])

  const filtersActive = [status, series, format, minScore].some((f) => f !== ALL) || query

  return (
    <div className="surface-creative min-h-full">
    <div className="mx-auto max-w-[1400px] px-4 py-6 md:px-8 md:py-8">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="font-display text-[34px] leading-tight font-extrabold tracking-[-1px]">Stories</h1>
          <p className="text-[14.5px] text-[#a9a69e]">Every candidate story, from Inbox to Published. Colour = series.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Tabs value={view} onValueChange={(v) => setView(v as "table" | "board")}>
            <TabsList className="h-11">
              <TabsTrigger value="board" className="h-9"><KanbanIcon /> Board</TabsTrigger>
              <TabsTrigger value="table" className="h-9"><TableIcon /> Table</TabsTrigger>
            </TabsList>
          </Tabs>
          <ScoutLauncher size="default" label="Find stories" className="h-11 rounded-xl px-4 font-display text-[15px] font-extrabold" />
        </div>
      </header>

      <div role="group" aria-label="Series" className="mb-3 flex flex-wrap gap-2">
        <button
          type="button"
          aria-pressed={series === ALL}
          onClick={() => setSeries(ALL)}
          className={cn(
            "h-9 rounded-full px-3.5 text-[13px] transition-colors",
            series === ALL ? "bg-foreground-warm font-semibold text-background-creative" : "border border-white/8 bg-card-creative text-[#e2dfd7] hover:border-white/20",
          )}
        >
          All series
        </button>
        {SERIES_STYLES.map((s) => (
          <button
            key={s.key}
            type="button"
            aria-pressed={series === s.label}
            onClick={() => setSeries(series === s.label ? ALL : s.label)}
            className={cn(
              "inline-flex h-9 items-center rounded-full px-3.5 transition-colors",
              series === s.label ? "bg-foreground-warm font-semibold text-background-creative" : "border border-white/8 bg-card-creative text-[#e2dfd7] hover:border-white/20",
            )}
          >
            <SeriesChip series={s.label} variant="filter" />
            <span className="num ml-2 text-[11.5px] opacity-60">{stories.filter((x) => x.series === s.label).length}</span>
          </button>
        ))}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-56">
          <SearchIcon className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter stories…" className="h-8 pl-8" />
        </div>
        <Filter value={status} onChange={setStatus} label="Status" options={STORY_STATUSES} />
        <Filter value={format} onChange={setFormat} label="Format" options={["Short", "Long"]} />
        <Filter value={minScore} onChange={setMinScore} label="Score" options={["6", "7", "8"]} format={(v) => `≥ ${v}`} />
        {filtersActive && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setQuery("")
              setStatus(ALL)
              setSeries(ALL)
              setFormat(ALL)
              setMinScore(ALL)
            }}
          >
            Clear
          </Button>
        )}
        <span className="ml-auto font-mono text-xs text-muted-foreground">{filtered.length} stories</span>
      </div>

      {isLoading ? (
        <LoadingState rows={8} />
      ) : error ? (
        <ErrorState error={error as Error} onRetry={() => void mutate()} />
      ) : stories.length === 0 ? (
        <EmptyState
          icon={LayersIcon}
          title="No stories yet"
          description="Run @scout to find story leads. They land here with status Inbox."
          action={<ScoutLauncher label="Find stories" />}
        />
      ) : filtered.length === 0 ? (
        <EmptyState icon={SearchIcon} title="No stories match these filters" />
      ) : view === "board" ? (
        <StoriesBoard stories={filtered} selectedId={openId} onOpen={setOpen} onMove={(s, to) => void move(s, to)} />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/7 bg-card-creative">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <SortHead label="Story" k="title" sort={sort} onSort={setSort} />
                <SortHead label="Status" k="status" sort={sort} onSort={setSort} />
                <TableHead>Series</TableHead>
                <TableHead>Format</TableHead>
                <SortHead label="Score" k="score" sort={sort} onSort={setSort} />
                <SortHead label="Gap" k="gap" sort={sort} onSort={setSort} />
                <SortHead label="Updated" k="updated" sort={sort} onSort={setSort} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((s) => (
                <TableRow
                  key={s.id}
                  tabIndex={0}
                  onClick={() => setOpen(s)}
                  onKeyDown={(e) => e.key === "Enter" && setOpen(s)}
                  className="cursor-pointer"
                >
                  <TableCell className="max-w-md">
                    <p className="truncate font-medium">{s.title}</p>
                    {s.hook && (
                      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <UnverifiedBadge compact />
                        <span className="truncate">{s.hook}</span>
                      </p>
                    )}
                  </TableCell>
                  <TableCell><StoryStatusBadge status={s.status} /></TableCell>
                  <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                    <span className="inline-flex items-center gap-2">
                      <SeriesDot series={s.series} /> {s.series ?? "—"}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{s.format ?? "—"}</TableCell>
                  <TableCell>{s.total_score !== null ? <ScoreBar value={s.total_score} /> : "—"}</TableCell>
                  <TableCell className="font-mono text-xs">{s.gap_score ?? "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{timeAgo(s.updated_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <StoryDrawer storyId={openId} onOpenChange={(open) => !open && setOpen(null)} onMove={(s, to) => void move(s, to)} />
    </div>
    </div>
  )
}

function Filter({
  value,
  onChange,
  label,
  options,
  format = (v) => v,
}: {
  value: string
  onChange: (v: string) => void
  label: string
  options: readonly string[]
  format?: (v: string) => string
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger size="sm" className={cn("h-8 text-xs", value !== ALL && "border-brand/50 text-foreground")}>
        <SelectValue placeholder={label}>{value === ALL ? label : `${label}: ${format(value)}`}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>All</SelectItem>
        {options.map((o) => (
          <SelectItem key={o} value={o}>{format(o)}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function SortHead({
  label,
  k,
  sort,
  onSort,
}: {
  label: string
  k: SortKey
  sort: { key: SortKey; desc: boolean }
  onSort: (s: { key: SortKey; desc: boolean }) => void
}) {
  const active = sort.key === k
  const Icon = sort.desc ? ArrowDownIcon : ArrowUpIcon
  return (
    <TableHead aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}>
      <button
        onClick={() => onSort({ key: k, desc: active ? !sort.desc : true })}
        className={cn("inline-flex items-center gap-1 hover:text-foreground", active && "text-foreground")}
      >
        {label}
        {active && <Icon className="size-3" />}
      </button>
    </TableHead>
  )
}
