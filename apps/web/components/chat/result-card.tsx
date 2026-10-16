"use client"

import { CircleAlertIcon, CircleSlashIcon } from "lucide-react"
import Link from "next/link"

import { ThumbnailBlock } from "@/components/blocks/thumbnail-block"
import { useStories } from "@/hooks/use-live"
import type { ChatMessageRecord, ResultStep, Story } from "@/lib/types"
import { cn } from "@/lib/utils"

const VIEW: Record<string, { href: string; label: string }> = {
  scout: { href: "/stories", label: "Stories" },
  outlier: { href: "/outliers", label: "Outliers" },
  researcher: { href: "/research", label: "Research" },
}

/** Results of a finished plan (SPEC §9 Chat). Scout's stories show as thumbnail ideas. */
export function ResultCard({ message }: { message: ChatMessageRecord }) {
  const steps = message.metadata.steps ?? []
  const stories = useStories()
  return (
    <div className="flex flex-col gap-4">
      {steps.map((step) => (
        <StepResult key={step.order} step={step} stories={stories.data} />
      ))}
    </div>
  )
}

/** A short headline; the full summary goes underneath in small text. */
function headline(step: ResultStep, picks: number): string {
  if (step.status !== "succeeded") return step.status === "failed" ? "failed" : step.status
  const found = /found (\d+)/i.exec(step.summary ?? "")
  if (step.agent === "scout" && found) return `found ${found[1]} ${found[1] === "1" ? "story" : "stories"}.${picks ? ` Top ${picks}:` : ""}`
  const first = (step.summary ?? "done").split(/(?<=[.;])\s/)[0].split(":")[0].trim()
  return first.length <= 90 ? first : "done"
}

function StepResult({ step, stories }: { step: ResultStep; stories: Story[] | undefined }) {
  const ok = step.status === "succeeded"
  const view = VIEW[step.agent]
  const picks =
    step.agent === "scout" && ok
      ? (step.items
          .map((item) => stories?.find((s) => s.id === item.id))
          .filter(Boolean)
          .slice(0, 4) as Story[])
      : []

  return (
    <section aria-label={`@${step.agent} results`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <span
          className={cn(
            "flex items-center gap-1 font-mono text-[13px]",
            ok ? "text-success-text" : step.status === "failed" ? "text-destructive-text" : "text-subtle-foreground",
          )}
        >
          {ok ? "✓" : step.status === "failed" ? <CircleAlertIcon className="size-3.5" /> : <CircleSlashIcon className="size-3.5" />} @{step.agent}
        </span>
        <span className="font-display text-[19px] leading-snug font-bold">{headline(step, picks.length)}</span>
        {view && ok && (
          <Link href={view.href} className="ml-auto text-[13.5px] text-brand-soft hover:underline">
            Open in {view.label} →
          </Link>
        )}
      </div>
      {step.summary && !picks.length && headline(step, 0) !== step.summary && (
        <p className="line-clamp-3 text-sm text-muted-foreground">{step.summary}</p>
      )}
      {step.error && <p className="text-sm text-destructive-text">{step.error}</p>}

      {picks.length > 0 ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {picks.map((story) => (
            <Link key={story.id} href={`/stories?story=${story.id}`} className="group flex flex-col gap-2">
              <ThumbnailBlock
                series={story.series}
                figure={story.hook_figure}
                caption={story.hook_caption}
                verified={story.hook_figure_verified}
                fallback={story.company ?? story.title}
                className="transition-transform group-hover:-translate-y-0.5"
              />
              <span className="flex items-center gap-2">
                <span className="min-w-0 truncate text-sm font-medium group-hover:underline">{story.company ?? story.title}</span>
                <span className="num ml-auto text-[13px] font-semibold">{story.total_score?.toFixed(1) ?? "—"}</span>
              </span>
            </Link>
          ))}
        </div>
      ) : (
        step.items.length > 0 && (
          <ul className="flex flex-col gap-1.5 rounded-[14px] bg-card-creative p-3">
            {step.items.map((item, i) => (
              <li key={`${item.id ?? i}`}>
                <Link href={item.href} className="group flex items-baseline gap-2 text-sm">
                  <span className="min-w-0 truncate group-hover:underline">{item.label}</span>
                  {item.detail && <span className="num ml-auto shrink-0 text-xs text-subtle-foreground">{item.detail}</span>}
                </Link>
              </li>
            ))}
          </ul>
        )
      )}

      <div className="flex flex-wrap items-center gap-3 font-mono text-[11.5px] text-subtle-foreground">
        {step.run_id && (
          <Link href={`/runs/${step.run_id}`} className="hover:text-brand-soft">
            run #{step.run_id}
          </Link>
        )}
        {step.youtube_units != null && <span>{step.youtube_units} YouTube units</span>}
      </div>
    </section>
  )
}
