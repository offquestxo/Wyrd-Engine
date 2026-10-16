"use client"

import { BookOpenTextIcon, ChevronDownIcon, ExternalLinkIcon, MessageSquareIcon } from "lucide-react"
import Link from "next/link"
import { useState } from "react"

import { SeriesChip } from "@/components/blocks/series"
import { ThumbnailBlock } from "@/components/blocks/thumbnail-block"
import { UnverifiedBadge } from "@/components/common/badges"
import { ErrorState, LoadingState } from "@/components/common/states"
import { useProposePlan } from "@/components/plans/propose-provider"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import { useStory } from "@/hooks/use-live"
import { STORY_STATUSES, type Story, type StoryStatus } from "@/lib/types"

const SCORE_LABELS: Record<string, string> = {
  drama: "Drama",
  twist: "Twist",
  relatability: "Relatability",
  visual_potential: "Visuals",
  hook_number: "Hook number",
  freshness: "Freshness",
}

const Chip = ({ children }: { children: React.ReactNode }) => (
  <span className="rounded-full bg-[#1e212b] px-2.5 py-1 text-[12.5px] text-[#d9d6ce]">{children}</span>
)

/** Story detail (creative): thumbnail idea, hook, scores as A-style data bars, sources, actions. */
export function StoryDrawer({
  storyId,
  onOpenChange,
  onMove,
}: {
  storyId: number | null
  onOpenChange: (open: boolean) => void
  onMove: (story: Story, status: StoryStatus) => void
}) {
  const { data: story, error, isLoading, mutate } = useStory(storyId)
  const propose = useProposePlan()
  const [showSources, setShowSources] = useState(false)

  const sources = story?.sources ?? []
  const primary = sources.filter((s) => s.source_type === "primary").length
  const researched = (story?.dossier_versions?.length ?? 0) > 0

  return (
    <Sheet open={storyId !== null} onOpenChange={onOpenChange}>
      <SheetContent className="surface-creative w-full overflow-y-auto border-l border-brand-soft/30 sm:max-w-[440px]">
        {isLoading ? (
          <div className="p-6">
            <SheetTitle className="sr-only">Loading story</SheetTitle>
            <LoadingState rows={6} />
          </div>
        ) : error ? (
          <div className="p-6">
            <SheetTitle className="sr-only">Story</SheetTitle>
            <ErrorState error={error as Error} onRetry={() => void mutate()} />
          </div>
        ) : story ? (
          <div className="flex flex-col gap-4 p-[18px] pt-12">
            <ThumbnailBlock
              size="lg"
              series={story.series}
              figure={story.hook_figure}
              caption={story.hook_caption}
              verified={story.hook_figure_verified}
              fallback={story.company ?? story.title}
            />
            {story.hook_figure && (
              <p className="-mt-2 text-[11.5px] text-subtle-foreground">
                {story.hook_figure_verified
                  ? "✓ Figure confirmed by the dossier's Key Numbers."
                  : "? Figure taken from the source text; not yet confirmed by a dossier."}
              </p>
            )}

            <div className="flex flex-col gap-1.5">
              <div className="flex items-start gap-2.5">
                <SheetTitle className="font-display text-[26px] leading-tight font-extrabold tracking-[-0.6px] text-foreground-warm">
                  {story.company ?? story.title}
                </SheetTitle>
                <span className="num ml-auto pt-1 text-[22px] font-semibold">{story.total_score?.toFixed(1) ?? "—"}</span>
              </div>
              {story.company && story.company !== story.title && <SheetDescription className="text-sm text-[#a9a69e]">{story.title}</SheetDescription>}
              {story.hook && (
                <p className="mt-1 text-[14.5px] leading-normal text-[#d9d6ce]">
                  <UnverifiedBadge compact /> {story.hook}
                </p>
              )}
              <div className="mt-1 flex flex-wrap gap-1.5">
                <SeriesChip series={story.series} />
                {story.format && <Chip>{story.format === "Long" ? "Long-form" : "Short"}</Chip>}
                <Chip>{story.status}</Chip>
                {story.outlier_ref && <Chip>from an outlier</Chip>}
              </div>
            </div>

            {story.scores && (
              <section aria-label="Scores" className="flex flex-col gap-[9px] border-t border-white/7 pt-3.5">
                <span className="font-mono text-[11.5px] tracking-[0.8px] text-[#a9a69e]">SCORES</span>
                {Object.entries(SCORE_LABELS).map(([key, label]) => {
                  const value = story.scores?.[key as keyof typeof story.scores]
                  if (typeof value !== "number") return null
                  return (
                    <div key={key} className="flex items-center gap-2.5 text-[13px]">
                      <span className="w-24 text-[#d9d6ce]">{label}</span>
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#262a36]">
                        <span className="block h-full rounded-full bg-foreground-warm" style={{ width: `${value * 10}%` }} />
                      </span>
                      <span className="num w-5 text-right">{value}</span>
                    </div>
                  )
                })}
                <div className="mt-1.5 flex flex-wrap gap-[18px] text-[13px] text-[#a9a69e]">
                  {story.gap_score != null && (
                    <span>
                      Gap score <b className="num font-medium text-foreground-warm">{story.gap_score}</b>
                    </span>
                  )}
                  <span>
                    Sources <b className="num font-medium text-foreground-warm">{sources.length}</b> ({primary} primary)
                  </span>
                </div>
              </section>
            )}

            <div className="flex flex-col gap-2">
              <Button
                className="h-[46px] rounded-xl bg-brand font-display text-base font-extrabold text-brand-foreground hover:bg-brand/90"
                onClick={() =>
                  void propose("researcher", { story_id: story.id, depth: "standard" }, `Research “${story.title}” (standard depth)`)
                }
              >
                <BookOpenTextIcon /> {researched ? "Research again" : "Research this"}
              </Button>
              <div className="grid grid-cols-2 gap-2">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" className="h-11 rounded-xl border-white/16 bg-transparent">
                      Move to… <ChevronDownIcon />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    {STORY_STATUSES.filter((s) => s !== story.status).map((s) => (
                      <DropdownMenuItem key={s} onSelect={() => onMove(story, s)}>
                        {s}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
                <Button
                  variant="outline"
                  className="h-11 rounded-xl border-white/16 bg-transparent"
                  aria-expanded={showSources}
                  onClick={() => setShowSources(!showSources)}
                  disabled={sources.length === 0}
                >
                  {showSources ? "Hide sources" : "Open sources"}
                </Button>
              </div>
            </div>

            {showSources && (
              <section aria-label="Sources" className="flex flex-col gap-2">
                {sources.map((s) => (
                  <a
                    key={s.id}
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex flex-col gap-1 rounded-xl bg-card-creative p-3 text-sm transition-colors hover:bg-[#1c1f29]"
                  >
                    <span className="flex items-start gap-1.5">
                      <span className="flex-1 break-words">{s.title ?? s.url}</span>
                      <ExternalLinkIcon className="mt-0.5 size-3.5 shrink-0 text-subtle-foreground" />
                    </span>
                    <span className="flex items-center gap-2 text-xs">
                      <span className={s.source_type === "primary" ? "text-success-text" : "text-subtle-foreground"}>{s.source_type}</span>
                      {s.excerpt && <span className="line-clamp-2 text-[#a9a69e]">“{s.excerpt}”</span>}
                    </span>
                  </a>
                ))}
              </section>
            )}

            {researched && (
              <section aria-label="Dossiers" className="flex flex-col gap-2 border-t border-white/7 pt-3.5">
                <span className="font-mono text-[11.5px] tracking-[0.8px] text-[#a9a69e]">DOSSIER</span>
                <div className="flex flex-wrap gap-2">
                  {story.dossier_versions!.map((v) => (
                    <Button key={v} variant="outline" size="sm" className="border-white/16 bg-transparent" asChild>
                      <Link href={`/research?story=${story.id}&v=${v}`}>
                        <BookOpenTextIcon /> v{v}
                      </Link>
                    </Button>
                  ))}
                </div>
              </section>
            )}

            {story.notes && (
              <section aria-label="Notes" className="flex flex-col gap-1 border-t border-white/7 pt-3.5">
                <span className="font-mono text-[11.5px] tracking-[0.8px] text-[#a9a69e]">NOTES</span>
                <p className="text-[13px] leading-5 text-[#a9a69e]">{story.notes}</p>
              </section>
            )}

            <Link
              href={`/chat?compose=${encodeURIComponent(`@researcher ${story.title} `)}`}
              className="flex items-center gap-1.5 text-[13px] text-brand-soft hover:underline"
            >
              <MessageSquareIcon className="size-3.5" /> Ask about it in Chat
            </Link>
          </div>
        ) : (
          <SheetTitle className="sr-only">Story</SheetTitle>
        )}
      </SheetContent>
    </Sheet>
  )
}
