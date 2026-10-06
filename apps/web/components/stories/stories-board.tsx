"use client"

import { useState } from "react"

import { UnverifiedBadge } from "@/components/common/badges"
import { STORY_STATUSES, type Story, type StoryStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Board grouped by status. Drag a card to another column to change its status. */
export function StoriesBoard({
  stories,
  onOpen,
  onMove,
}: {
  stories: Story[]
  onOpen: (story: Story) => void
  onMove: (story: Story, status: StoryStatus) => void
}) {
  const [dragId, setDragId] = useState<number | null>(null)
  const [over, setOver] = useState<StoryStatus | null>(null)

  return (
    <div className="flex gap-3 overflow-x-auto pb-4">
      {STORY_STATUSES.map((status) => {
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
              "flex w-60 shrink-0 flex-col rounded-lg border bg-muted/20 transition-colors",
              over === status && "border-brand/50 bg-brand-muted",
            )}
          >
            <div className="flex items-center justify-between px-3 py-2.5 text-xs font-medium">
              {status}
              <span className="font-mono text-muted-foreground">{column.length}</span>
            </div>
            <div className="flex min-h-24 flex-col gap-2 px-2 pb-2">
              {column.map((story) => (
                <button
                  key={story.id}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData("text/x-story-id", String(story.id))
                    e.dataTransfer.effectAllowed = "move"
                    setDragId(story.id)
                  }}
                  onDragEnd={() => setDragId(null)}
                  onClick={() => onOpen(story)}
                  className={cn(
                    "rounded-md border bg-card p-2.5 text-left transition-colors hover:border-brand/40",
                    dragId === story.id && "opacity-50",
                  )}
                >
                  <p className="text-sm font-medium">{story.title}</p>
                  {story.hook && (
                    <div className="mt-1">
                      <UnverifiedBadge compact />
                      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{story.hook}</p>
                    </div>
                  )}
                  <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-muted-foreground">
                    <span>{story.series ?? "—"}</span>
                    <span className="text-foreground/80">{story.total_score ?? "—"}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
