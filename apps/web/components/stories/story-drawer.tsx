"use client"

import { ArrowRightIcon, BookOpenTextIcon, ExternalLinkIcon, StarIcon } from "lucide-react"
import Link from "next/link"
import { toast } from "sonner"

import { ScoreBar, StoryStatusBadge } from "@/components/common/badges"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { totalScore } from "@/lib/format"
import type { Story } from "@/lib/types"

const SCORE_LABELS: Record<string, string> = {
  drama: "Drama",
  twist: "Twist",
  relatability: "Relatability",
  visual_potential: "Visual potential",
  hook_number: "Hook number",
  freshness: "Freshness",
}

export function StoryDrawer({
  story,
  onOpenChange,
  onMove,
}: {
  story: Story | null
  onOpenChange: (open: boolean) => void
  onMove: (story: Story, status: Story["status"]) => void
}) {
  return (
    <Sheet open={!!story} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {story && (
          <>
            <SheetHeader className="border-b">
              <div className="flex items-center gap-2">
                <StoryStatusBadge status={story.status} />
                <Badge variant="outline" className="text-[10px]">{story.series}</Badge>
                <Badge variant="outline" className="text-[10px]">{story.format}</Badge>
                {story.from_outlier && <Badge variant="outline" className="text-[10px] text-brand">from outlier</Badge>}
              </div>
              <SheetTitle className="text-lg">{story.title}</SheetTitle>
              <SheetDescription>{story.company}</SheetDescription>
            </SheetHeader>

            <div className="space-y-6 px-4 pb-6">
              <section>
                <p className="mb-1 text-[11px] tracking-wide text-muted-foreground uppercase">Hook</p>
                <p className="text-sm">“{story.hook}”</p>
              </section>

              <section>
                <div className="mb-2 flex items-baseline justify-between">
                  <p className="text-[11px] tracking-wide text-muted-foreground uppercase">Scores</p>
                  <p className="font-mono text-xs">
                    avg {totalScore(story.scores)}
                    {story.gap_score !== null && <span className="text-brand"> · gap {story.gap_score}</span>}
                  </p>
                </div>
                <div className="space-y-1.5">
                  {Object.entries(story.scores).map(([key, value]) => (
                    <div key={key} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{SCORE_LABELS[key]}</span>
                      <ScoreBar value={value} />
                    </div>
                  ))}
                </div>
              </section>

              <section>
                <p className="mb-2 text-[11px] tracking-wide text-muted-foreground uppercase">
                  Sources ({story.sources.length})
                </p>
                {story.sources.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No sources yet. @researcher adds them.</p>
                ) : (
                  <ul className="space-y-2">
                    {story.sources.map((s) => (
                      <li key={s.id} className="rounded-md border p-2.5 text-sm">
                        <a href={s.url} target="_blank" rel="noreferrer" className="flex items-start gap-1.5 hover:text-brand">
                          <span className="flex-1">{s.title}</span>
                          <ExternalLinkIcon className="mt-0.5 size-3 shrink-0" />
                        </a>
                        <div className="mt-1 flex items-center gap-2">
                          <Badge variant="outline" className={s.source_type === "primary" ? "border-success/40 text-[10px] text-success" : "text-[10px]"}>
                            {s.source_type}
                          </Badge>
                          {s.excerpt && <span className="truncate text-xs text-muted-foreground">“{s.excerpt}”</span>}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <p className="mb-2 text-[11px] tracking-wide text-muted-foreground uppercase">Dossier versions</p>
                {story.dossier_versions.length === 0 ? (
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
                  onClick={() => toast.info("Research runs start from a plan card in Phase 6.")}
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
        )}
      </SheetContent>
    </Sheet>
  )
}
