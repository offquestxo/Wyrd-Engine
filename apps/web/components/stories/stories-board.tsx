"use client"

import { useMemo, useState } from "react"

import { ThumbnailBlock } from "@/components/blocks/thumbnail-block"
import { useRuns } from "@/hooks/use-live"
import { STORY_STATUSES, type RunRecord, type Story, type StoryStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Live @researcher runs by story id, so Researching cards can show real progress. */
function useResearchProgress(): Map<number, RunRecord> {
  const runs = useRuns("status=running,queued&limit=20")
  return useMemo(() => {
    const out = new Map<number, RunRecord>()
    for (const run of runs.data ?? []) {
      const id = Number(run.params?.story_id)
      if (run.agent === "researcher" && id) out.set(id, run)
    }
    return out
  }, [runs.data])
}

/**
 * Board grouped by status (creative style): each card is a thumbnail idea in its series colour.
 * Drag a card to another column to change its status. Archived only shows when it has stories.
 */
export function StoriesBoard({
  stories,
  onOpen,
  onMove,
  selectedId,
}: {
  stories: Story[]
  onOpen: (story: Story) => void
  onMove: (story: Story, status: StoryStatus) => void
  selectedId?: number | null
}) {
  const [dragId, setDragId] = useState<number | null>(null)
  const [over, setOver] = useState<StoryStatus | null>(null)
  const research = useResearchProgress()
  const columns = STORY_STATUSES.filter((s) => s !== "Archived" || stories.some((x) => x.status === s))

  return (
    <div className="-mx-4 overflow-x-auto px-4 pb-4 md:mx-0 md:px-0">
      <div className="flex gap-3.5">
        {columns.map((status) => {
          const column = stories.filter((s) => s.status === status)
          return (
            <div
              key={status}
              onDragOver={(e) => {
                e.preventDefault()
                setOver(status)
              }}
              onDragLeave={() => setOver(null)}
              onDrop={(e) => {
                e.preventDefault()
                // The dragged id travels with the event (state may not have re-rendered yet).
                const id = Number(e.dataTransfer.getData("text/x-story-id")) || dragId
                const story = stories.find((s) => s.id === id)
                if (story && story.status !== status) onMove(story, status)
                setDragId(null)
                setOver(null)
              }}
              className={cn(
                "flex w-[248px] shrink-0 flex-col gap-3 rounded-2xl border border-white/6 bg-[#101219] p-3 transition-colors",
                over === status && "border-brand-soft/50 bg-brand-muted",
              )}
            >
              <div className="flex items-center gap-2 px-1 pt-0.5">
                <span className="font-display text-base font-extrabold">{status}</span>
                <span className="num rounded-full bg-[#1c1f29] px-2 py-px text-xs text-[#a9a69e]">{column.length}</span>
              </div>
              <div className="flex min-h-24 flex-col gap-3">
                {column.length === 0 && (
                  <p className="rounded-xl border border-dashed border-white/8 px-3 py-6 text-center text-xs text-subtle-foreground">
                    Drop a story here
                  </p>
                )}
                {column.map((story) => {
                  const run = research.get(story.id)
                  const pct = run?.progress != null ? Math.round(run.progress * 100) : null
                  return (
                    <button
                      key={story.id}
                      type="button"
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData("text/x-story-id", String(story.id))
                        e.dataTransfer.effectAllowed = "move"
                        setDragId(story.id)
                      }}
                      onDragEnd={() => setDragId(null)}
                      onClick={() => onOpen(story)}
                      aria-label={`${story.company ?? story.title}, ${story.status}${run ? ", being researched" : ""}`}
                      className={cn(
                        "flex flex-col gap-2.5 rounded-[14px] border border-white/7 bg-card-creative p-2.5 text-left transition-[transform,border-color] hover:-translate-y-0.5 hover:border-white/15 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                        dragId === story.id && "opacity-50",
                        run && "border-transparent glow-live",
                        selectedId === story.id && "border-brand-soft/50",
                      )}
                    >
                      <ThumbnailBlock
                        series={story.series}
                        figure={story.hook_figure}
                        caption={story.hook_caption}
                        verified={story.hook_figure_verified}
                        fallback={story.company ?? story.title}
                      />
                      <div className="flex items-center gap-2 px-0.5">
                        <span className="line-clamp-2 text-[15px] leading-snug font-semibold">{story.company ?? story.title}</span>
                        <span className="num ml-auto shrink-0 text-[13.5px] font-semibold">{story.total_score?.toFixed(1) ?? "—"}</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5 px-0.5 text-xs text-[#a9a69e]">
                        <span>{story.series ?? "No series"}</span>
                        <span aria-hidden>·</span>
                        <span>{story.format ?? "—"}</span>
                        {run && (
                          <span className="mt-1 flex basis-full items-center gap-2">
                            <span className="h-[5px] flex-1 overflow-hidden rounded-full bg-[#262a36]">
                              <span
                                className={cn("block h-full bg-live", pct == null && "w-1/3 animate-pulse")}
                                style={pct != null ? { width: `${Math.max(pct, 3)}%` } : undefined}
                              />
                            </span>
                            <span className="num text-live-text">researching</span>
                          </span>
                        )}
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
