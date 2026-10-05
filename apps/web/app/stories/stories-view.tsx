"use client"

import { ArrowDownIcon, ArrowUpIcon, KanbanIcon, LayersIcon, SearchIcon, TableIcon } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { ScoreBar, StoryStatusBadge } from "@/components/common/badges"
import { PageHeader } from "@/components/common/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { StoriesBoard } from "@/components/stories/stories-board"
import { StoryDrawer } from "@/components/stories/story-drawer"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useDemo } from "@/hooks/use-demo"
import { useLocalState } from "@/hooks/use-local-state"
import { timeAgo, totalScore } from "@/lib/format"
import { MOCK_STORIES } from "@/lib/mock"
import { SERIES, STORY_STATUSES, type Story, type StoryStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

type SortKey = "title" | "status" | "score" | "gap" | "updated"
const ALL = "all"

export function StoriesView() {
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()
  const { data, isLoading, error, retry } = useDemo(MOCK_STORIES, [])
  // Local status changes layered over the loaded stories (persisted in Phase 3).
  const [edited, setStories] = useState<Story[] | null>(null)
  const stories = useMemo(() => edited ?? data ?? [], [edited, data])
  const [view, setView] = useLocalState<"table" | "board">("wyrd.storiesView", "table")
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState<string>(ALL)
  const [series, setSeries] = useState<string>(ALL)
  const [format, setFormat] = useState<string>(ALL)
  const [minScore, setMinScore] = useState<string>(ALL)
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "score", desc: true })

  const openId = Number(params.get("story")) || null
  const openStory = stories.find((s) => s.id === openId) ?? null
  const setOpen = (story: Story | null) => {
    const next = new URLSearchParams(params)
    if (story) next.set("story", String(story.id))
    else next.delete("story")
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false })
  }

  const move = (story: Story, to: StoryStatus) => {
    setStories(stories.map((s) => (s.id === story.id ? { ...s, status: to, updated_at: new Date().toISOString() } : s)))
    toast.success(`${story.title} → ${to}`, { description: "Sample data: saved locally until Phase 3." })
  }

  const filtered = useMemo(() => {
    const q = query.toLowerCase()
    const rows = stories.filter(
      (s) =>
        (status === ALL || s.status === status) &&
        (series === ALL || s.series === series) &&
        (format === ALL || s.format === format) &&
        (minScore === ALL || totalScore(s.scores) >= Number(minScore)) &&
        (!q || `${s.title} ${s.company} ${s.hook}`.toLowerCase().includes(q)),
    )
    const value = (s: Story): string | number => {
      switch (sort.key) {
        case "title": return s.title.toLowerCase()
        case "status": return STORY_STATUSES.indexOf(s.status)
        case "score": return totalScore(s.scores)
        case "gap": return s.gap_score ?? -1
        case "updated": return s.updated_at
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
    <div className="mx-auto max-w-7xl px-8 py-8">
      <PageHeader
        title="Stories"
        description="Every candidate story, from Inbox to Published."
        sample
        actions={
          <Tabs value={view} onValueChange={(v) => setView(v as "table" | "board")}>
            <TabsList>
              <TabsTrigger value="table"><TableIcon /> Table</TabsTrigger>
              <TabsTrigger value="board"><KanbanIcon /> Board</TabsTrigger>
            </TabsList>
          </Tabs>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-56">
          <SearchIcon className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter stories…" className="h-8 pl-8" />
        </div>
        <Filter value={status} onChange={setStatus} label="Status" options={STORY_STATUSES} />
        <Filter value={series} onChange={setSeries} label="Series" options={SERIES} />
        <Filter value={format} onChange={setFormat} label="Format" options={["Short", "Long"]} />
        <Filter value={minScore} onChange={setMinScore} label="Score" options={["6", "7", "8"]} format={(v) => `≥ ${v}`} />
        {filtersActive && (
          <Button variant="ghost" size="sm" onClick={() => { setQuery(""); setStatus(ALL); setSeries(ALL); setFormat(ALL); setMinScore(ALL) }}>
            Clear
          </Button>
        )}
        <span className="ml-auto font-mono text-xs text-muted-foreground">{filtered.length} stories</span>
      </div>

      {isLoading ? (
        <LoadingState rows={8} />
      ) : error ? (
        <ErrorState error={error} onRetry={retry} />
      ) : stories.length === 0 ? (
        <EmptyState
          icon={LayersIcon}
          title="No stories yet"
          description="Run @scout to find story leads. They land here with status Inbox."
          action={<Button size="sm" onClick={() => router.push("/chat?compose=%40scout%20")}>Run @scout</Button>}
        />
      ) : filtered.length === 0 ? (
        <EmptyState icon={SearchIcon} title="No stories match these filters" />
      ) : view === "board" ? (
        <StoriesBoard stories={filtered} onOpen={setOpen} onMove={move} />
      ) : (
        <div className="overflow-hidden rounded-lg border">
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
                    <p className="font-medium">{s.title}</p>
                    <p className="truncate text-xs text-muted-foreground">{s.hook}</p>
                  </TableCell>
                  <TableCell><StoryStatusBadge status={s.status} /></TableCell>
                  <TableCell className="text-xs text-muted-foreground">{s.series}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{s.format}</TableCell>
                  <TableCell><ScoreBar value={totalScore(s.scores)} /></TableCell>
                  <TableCell className="font-mono text-xs">{s.gap_score ?? "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{timeAgo(s.updated_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <StoryDrawer story={openStory} onOpenChange={(open) => !open && setOpen(null)} onMove={move} />
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
