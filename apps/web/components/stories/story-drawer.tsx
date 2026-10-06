"use client"

import { ArrowRightIcon, BookOpenTextIcon, ExternalLinkIcon, StarIcon } from "lucide-react"
import Link from "next/link"

import { ScoreBar, StoryStatusBadge, UnverifiedBadge } from "@/components/common/badges"
import { ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useProposePlan } from "@/components/plans/propose-provider"
import { useStory } from "@/hooks/use-live"
import type { Story, StoryStatus } from "@/lib/types"

const SCORE_LABELS: Record<string, string> = {
  drama: "Drama",
  twist: "Twist",
  relatability: "Relatability",
  visual_potential: "Visual potential",
  hook_number: "Hook number",
  freshness: "Freshness",
}

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

  return (
    <Sheet open={storyId !== null} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {isLoading ? (
          <div className="p-6"><SheetTitle className="sr-only">Loading story</SheetTitle><LoadingState rows={6} /></div>
        ) : error ? (
          <div className="p-6"><SheetTitle className="sr-only">Story</SheetTitle><ErrorState error={error as Error} onRetry={() => void mutate()} /></div>
        ) : story ? (
          <>
            <SheetHeader className="border-b">
              <div className="flex flex-wrap items-center gap-2">
                <StoryStatusBadge status={story.status} />
                {story.series && <Badge variant="outline" className="text-[10px]">{story.series}</Badge>}
                {story.format && <Badge variant="outline" className="text-[10px]">{story.format}</Badge>}
                {story.outlier_ref && <Badge variant="outline" className="text-[10px] text-brand">from outlier</Badge>}
              </div>
              <SheetTitle className="text-lg">{story.title}</SheetTitle>
              {story.company && <SheetDescription>{story.company}</SheetDescription>}
            </SheetHeader>

            <div className="space-y-6 px-4 pb-6">
              {story.hook && (
                <section>
                  <div className="mb-1 flex items-center gap-2">
                    <p className="text-[11px] tracking-wide text-muted-foreground uppercase">Hook</p>
                    <UnverifiedBadge />
                  </div>
                  <p className="text-sm">“{story.hook}”</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Written by @scout from the source headline. Check it against a dossier before using it.
                  </p>
                </section>
              )}

              {story.scores && (
                <section>
                  <div className="mb-2 flex items-baseline justify-between">
                    <p className="text-[11px] tracking-wide text-muted-foreground uppercase">Scores</p>
                    <p className="font-mono text-xs">
                      {story.total_score !== null && <>score {story.total_score}</>}
                      {story.gap_score !== null && <span className="text-brand"> · gap {story.gap_score}</span>}
                    </p>
                  </div>
                  <div className="space-y-1.5">
                    {Object.entries(SCORE_LABELS).map(([key, label]) =>
                      typeof story.scores?.[key as keyof typeof story.scores] === "number" ? (
                        <div key={key} className="flex items-center justify-between text-sm">
                          <span className="text-muted-foreground">{label}</span>
                          <ScoreBar value={story.scores[key as keyof typeof story.scores] as number} />
                        </div>
                      ) : null,
                    )}
                  </div>
                </section>
              )}

              <section>
                <p className="mb-2 text-[11px] tracking-wide text-muted-foreground uppercase">
                  Sources ({story.sources?.length ?? 0})
                </p>
                {!story.sources?.length ? (
                  <p className="text-sm text-muted-foreground">No sources yet. @researcher adds them.</p>
                ) : (
                  <ul className="space-y-2">
                    {story.sources.map((s) => (
                      <li key={s.id} className="rounded-md border p-2.5 text-sm">
                        <a href={s.url} target="_blank" rel="noreferrer" className="flex items-start gap-1.5 hover:text-brand">
                          <span className="flex-1 break-words">{s.title ?? s.url}</span>
                          <ExternalLinkIcon className="mt-0.5 size-3 shrink-0" />
                        </a>
                        <div className="mt-1 flex items-center gap-2">
                          <Badge
                            variant="outline"
                            className={s.source_type === "primary" ? "border-success/40 text-[10px] text-success" : "text-[10px]"}
                          >
                            {s.source_type}
                          </Badge>
                          {s.excerpt && <span className="line-clamp-2 text-xs text-muted-foreground">“{s.excerpt}”</span>}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {story.notes && (
                <section>
                  <p className="mb-1 text-[11px] tracking-wide text-muted-foreground uppercase">Notes</p>
                  <p className="text-xs leading-5 text-muted-foreground">{story.notes}</p>
                </section>
              )}

              <section>
                <p className="mb-2 text-[11px] tracking-wide text-muted-foreground uppercase">Dossier versions</p>
                {!story.dossier_versions?.length ? (
                  <p className="text-sm text-muted-foreground">No dossier yet.</p>
                ) : (
                  <div className="flex gap-2">
                    {story.dossier_versions.map((v) => (
                      <Button key={v} variant="outline" size="sm" asChild>
                        <Link href={`/research?story=${story.id}&v=${v}`}><BookOpenTextIcon /> v{v}</Link>
                      </Button>
                    ))}
                  </div>
                )}
              </section>

              <section className="flex flex-wrap gap-2 border-t pt-4">
                <Button
                  size="sm"
                  className="bg-brand text-brand-foreground hover:bg-brand/90"
                  onClick={() =>
                    void propose("researcher", { story_id: story.id, depth: "standard" }, `Research “${story.title}” (standard depth)`)
                  }
                >
                  <BookOpenTextIcon /> Research this
                </Button>
                {story.status !== "Shortlisted" && (
                  <Button size="sm" variant="outline" onClick={() => onMove(story, "Shortlisted")}>
                    <StarIcon /> Move to Shortlisted
                  </Button>
                )}
                <Button size="sm" variant="ghost" asChild>
                  <Link href={`/chat?compose=${encodeURIComponent(`@researcher ${story.title} `)}`}>
                    Ask in chat <ArrowRightIcon />
                  </Link>
                </Button>
              </section>
            </div>
          </>
        ) : (
          <SheetTitle className="sr-only">Story</SheetTitle>
        )}
      </SheetContent>
    </Sheet>
  )
}
