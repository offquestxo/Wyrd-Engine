"use client"

import { BookOpenTextIcon, CopyIcon, ExternalLinkIcon, FileTextIcon, FlagIcon } from "lucide-react"
import { useSearchParams } from "next/navigation"
import { useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { toast } from "sonner"

import { SampleBadge } from "@/components/common/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useDemo } from "@/hooks/use-demo"
import { timeAgo } from "@/lib/format"
import { MOCK_DOSSIERS } from "@/lib/mock"
import type { Dossier } from "@/lib/types"
import { cn } from "@/lib/utils"

export function ResearchView() {
  const params = useSearchParams()
  const { data, isLoading, error, retry } = useDemo(MOCK_DOSSIERS, [])
  const [chosenId, setActiveId] = useState<number | null>(null)
  const [chosenVersion, setVersion] = useState<number | null>(null)

  // Default selection: the story from ?story=, else the newest dossier.
  const initial = data?.find((d) => d.story_id === Number(params.get("story"))) ?? data?.[0]
  const activeId = chosenId ?? initial?.id ?? null
  const dossier = data?.find((d) => d.id === activeId)
  const version = chosenVersion ?? (Number(params.get("v")) || dossier?.version || null)

  const copy = async () => {
    if (!dossier) return
    try {
      await navigator.clipboard.writeText(dossier.markdown)
      toast.success("Dossier copied", { description: "Paste it into your Script Room project." })
    } catch {
      toast.error("Clipboard unavailable in this browser context.")
    }
  }

  return (
    <div className="flex h-full">
      <div className="flex w-56 shrink-0 flex-col border-r">
        <div className="flex h-14 items-center gap-2 px-4 text-sm font-medium">
          Dossiers <SampleBadge />
        </div>
        <div className="flex-1 space-y-0.5 overflow-y-auto px-2">
          {isLoading ? (
            <LoadingState rows={3} className="px-2" />
          ) : (
            data?.map((d) => (
              <button
                key={d.id}
                onClick={() => {
                  setActiveId(d.id)
                  setVersion(d.version)
                }}
                className={cn("w-full rounded-md px-2.5 py-2 text-left hover:bg-muted", d.id === activeId && "bg-muted")}
              >
                <p className="text-sm">{d.story_title}</p>
                <p className="font-mono text-[11px] text-muted-foreground">
                  v{d.version} · {timeAgo(d.created_at)}
                  {d.flags > 0 && <span className="text-warning"> · {d.flags} flag</span>}
                </p>
              </button>
            ))
          )}
        </div>
      </div>

      <div className="min-w-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-8"><LoadingState rows={10} /></div>
        ) : error ? (
          <div className="p-8"><ErrorState error={error} onRetry={retry} /></div>
        ) : !dossier ? (
          <div className="p-8">
            <EmptyState
              icon={BookOpenTextIcon}
              title="No dossiers yet"
              description="Run @researcher on a story. Dossiers appear here and export to research/<story>/dossier.md."
            />
          </div>
        ) : (
          <div className="flex">
            <article className="min-w-0 flex-1 px-8 py-8">
              <div className="mb-6 flex flex-wrap items-center gap-2">
                <Select value={String(version)} onValueChange={(v) => setVersion(Number(v))}>
                  <SelectTrigger size="sm" className="h-8 w-28 font-mono text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {dossier.versions.map((v) => <SelectItem key={v} value={String(v)}>version {v}</SelectItem>)}
                  </SelectContent>
                </Select>
                {dossier.flags > 0 && (
                  <Badge variant="outline" className="gap-1 border-warning/40 text-warning">
                    <FlagIcon className="size-3" /> {dossier.flags} second-opinion flag
                  </Badge>
                )}
                <div className="ml-auto flex gap-2">
                  <Button size="sm" variant="outline" onClick={copy}><CopyIcon /> Copy for Script Room</Button>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span>
                        <Button size="sm" variant="ghost" disabled><FileTextIcon /> Open exported file</Button>
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>research/{dossier.slug}/dossier.md, exported in Phase 6</TooltipContent>
                  </Tooltip>
                </div>
              </div>
              <div className="prose-dossier max-w-3xl">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{dossier.markdown}</ReactMarkdown>
              </div>
              {/* Narrower screens: sources follow the dossier instead of a sidebar. */}
              <div className="mt-10 max-w-3xl border-t pt-6 2xl:hidden">
                <SourceList sources={dossier.sources} />
              </div>
            </article>
            <aside className="sticky top-0 hidden h-dvh w-72 shrink-0 overflow-y-auto border-l px-4 py-8 2xl:block">
              <SourceList sources={dossier.sources} />
            </aside>
          </div>
        )}
      </div>
    </div>
  )
}

function SourceList({ sources }: { sources: Dossier["sources"] }) {
  return (
    <>
      <p className="mb-3 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        Sources ({sources.length})
      </p>
      {sources.length === 0 ? (
        <p className="text-xs text-muted-foreground">No sources in this version.</p>
      ) : (
        <ol className="space-y-3">
          {sources.map((s) => (
            <li key={s.n} className="text-xs">
              <a href={s.url} target="_blank" rel="noreferrer" className="group flex gap-2 hover:text-brand">
                <span className="font-mono text-muted-foreground">[{s.n}]</span>
                <span className="flex-1 leading-5">
                  {s.title}
                  <ExternalLinkIcon className="ml-1 inline size-3 opacity-0 group-hover:opacity-100" />
                </span>
              </a>
              {s.primary && (
                <Badge variant="outline" className="mt-1 ml-6 border-success/40 text-[10px] text-success">
                  primary
                </Badge>
              )}
            </li>
          ))}
        </ol>
      )}
    </>
  )
}
