"use client"

import {
  BookOpenTextIcon,
  CheckCircle2Icon,
  CopyIcon,
  ExternalLinkIcon,
  FileTextIcon,
  FlagIcon,
  ShieldCheckIcon,
} from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { toast } from "sonner"
import useSWR from "swr"

import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useEngineEvent } from "@/hooks/use-events"
import { api, fetcher } from "@/lib/api"
import { timeAgo } from "@/lib/format"
import type { DossierDetail, DossierSource, DossierSummary } from "@/lib/types"
import { cn } from "@/lib/utils"

export function ResearchView() {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const list = useSWR<DossierSummary[]>("/api/dossiers", fetcher)
  const storyId = Number(params.get("story")) || list.data?.[0]?.story_id || null
  const version = Number(params.get("v")) || null
  const detail = useSWR<DossierDetail>(
    storyId ? `/api/dossiers/${storyId}${version ? `?version=${version}` : ""}` : null,
    fetcher,
  )
  useEngineEvent(["dossier.saved"], () => {
    void list.mutate()
    void detail.mutate()
  })

  const select = (story: number, v?: number) => {
    const next = new URLSearchParams(params.toString())
    next.set("story", String(story))
    if (v) next.set("v", String(v))
    else next.delete("v")
    router.replace(`${pathname}?${next.toString()}`, { scroll: false })
  }

  const dossier = detail.data
  const copy = async () => {
    if (!dossier) return
    try {
      await navigator.clipboard.writeText(dossier.markdown)
      toast.success("Dossier copied", { description: "Paste it into your Script Room project." })
    } catch {
      toast.error("Clipboard unavailable in this browser context.")
    }
  }
  const openFile = async () => {
    if (!dossier) return
    try {
      const res = await api<{ path: string }>(`/api/dossiers/${dossier.story_id}/open`, { method: "POST" })
      toast.success("Opened in Finder", { description: res.path })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col border-r md:flex">
        <div className="flex h-14 items-center px-4 text-sm font-medium">Dossiers</div>
        <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {list.isLoading ? (
            <LoadingState rows={3} className="px-2" />
          ) : list.error ? (
            <p className="px-2 py-4 text-xs text-destructive">Couldn&apos;t load dossiers.</p>
          ) : !list.data?.length ? (
            <p className="px-2 py-4 text-xs text-muted-foreground">No dossiers yet.</p>
          ) : (
            list.data.map((d) => (
              <button
                key={d.story_id}
                onClick={() => select(d.story_id)}
                className={cn(
                  "w-full rounded-md px-2.5 py-2 text-left hover:bg-muted",
                  d.story_id === storyId && "bg-muted",
                )}
              >
                <p className="truncate text-sm">{d.story_title}</p>
                <p className="font-mono text-[11px] text-muted-foreground">
                  v{d.version} · {timeAgo(d.created_at)} · {d.excerpt_check.passed} verified
                  {d.flags > 0 && <span className="text-warning"> · {d.flags} flags</span>}
                </p>
              </button>
            ))
          )}
        </div>
      </aside>

      <div className="min-w-0 flex-1 overflow-y-auto">
        {list.isLoading || (storyId && detail.isLoading) ? (
          <div className="p-8">
            <LoadingState rows={10} />
          </div>
        ) : list.error || detail.error ? (
          <div className="p-8">
            <ErrorState
              error={(list.error ?? detail.error) as Error}
              onRetry={() => {
                void list.mutate()
                void detail.mutate()
              }}
            />
          </div>
        ) : !dossier ? (
          <div className="p-8">
            <EmptyState
              icon={BookOpenTextIcon}
              title="No dossiers yet"
              description="Open a story and click “Research this”, or type @researcher in Chat. Dossiers appear here and export to research/<story>/dossier.md."
              action={
                <Button size="sm" variant="outline" asChild>
                  <Link href="/stories">Go to Stories</Link>
                </Button>
              }
            />
          </div>
        ) : (
          <div className="flex">
            <article className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
              <div className="mb-6 flex flex-wrap items-center gap-2">
                {/* Phones: pick the dossier here instead of the sidebar. */}
                {list.data && list.data.length > 1 && (
                  <Select value={String(dossier.story_id)} onValueChange={(v) => select(Number(v))}>
                    <SelectTrigger size="sm" className="h-8 max-w-48 md:hidden">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {list.data.map((d) => (
                        <SelectItem key={d.story_id} value={String(d.story_id)}>
                          {d.story_title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                <Select value={String(dossier.version)} onValueChange={(v) => select(dossier.story_id, Number(v))}>
                  <SelectTrigger size="sm" className="h-8 w-32 font-mono text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[...dossier.versions].reverse().map((v) => (
                      <SelectItem key={v} value={String(v)}>
                        version {v}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Badge variant="outline" className="gap-1 border-success/40 text-success">
                  <ShieldCheckIcon className="size-3" /> {dossier.excerpt_check.passed} verified
                  {dossier.excerpt_check.failed > 0 && ` · ${dossier.excerpt_check.failed} unverified`}
                </Badge>
                {dossier.flags > 0 && (
                  <Badge variant="outline" className="gap-1 border-warning/40 text-warning">
                    <FlagIcon className="size-3" /> {dossier.flags} second-opinion flags
                  </Badge>
                )}
                <div className="flex w-full gap-2 sm:ml-auto sm:w-auto">
                  <Button size="sm" variant="outline" onClick={copy}>
                    <CopyIcon /> Copy for Script Room
                  </Button>
                  <Button size="sm" variant="ghost" onClick={openFile} title={dossier.export_path ?? undefined}>
                    <FileTextIcon /> Open exported file
                  </Button>
                </div>
              </div>
              <p className="mb-6 text-xs text-muted-foreground">
                Story{" "}
                <Link href={`/stories?story=${dossier.story_id}`} className="text-brand hover:underline">
                  #{dossier.story_id}
                </Link>{" "}
                · {timeAgo(dossier.created_at)}
                {dossier.run_id && (
                  <>
                    {" "}
                    · from{" "}
                    <Link href={`/runs/${dossier.run_id}`} className="text-brand hover:underline">
                      run #{dossier.run_id}
                    </Link>
                  </>
                )}
                {dossier.export_path && <span className="font-mono"> · {dossier.export_path.split("/").slice(-3).join("/")}</span>}
              </p>
              <div className="prose-dossier max-w-3xl overflow-x-auto">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{dossier.markdown}</ReactMarkdown>
              </div>
              <Review dossier={dossier} />
              {/* Narrower screens: sources follow the dossier instead of a sidebar. */}
              <div className="mt-10 max-w-3xl border-t pt-6 2xl:hidden">
                <SourceList sources={dossier.sources} />
              </div>
            </article>
            <aside className="sticky top-0 hidden h-dvh w-80 shrink-0 overflow-y-auto border-l px-4 py-8 2xl:block">
              <SourceList sources={dossier.sources} />
            </aside>
          </div>
        )}
      </div>
    </div>
  )
}

/** Second-opinion flags and what the researcher did about each one. */
function Review({ dossier }: { dossier: DossierDetail }) {
  const flags = dossier.second_opinion?.flags ?? []
  const resolutions = dossier.second_opinion?.resolutions ?? []
  if (!flags.length && !resolutions.length) return null
  return (
    <section className="mt-10 max-w-3xl space-y-3 border-t pt-6">
      <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        Second opinion ({flags.length} flags)
      </p>
      {flags.length > 0 && (
        <ul className="space-y-2">
          {flags.map((f, i) => (
            <li key={i} className="rounded-md border px-3 py-2 text-xs">
              <span
                className={cn(
                  "mr-2 font-mono uppercase",
                  f.severity === "high" ? "text-destructive" : f.severity === "medium" ? "text-warning" : "text-muted-foreground",
                )}
              >
                {f.severity}
              </span>
              <span className="text-foreground/90">{f.claim}</span>
              <p className="mt-1 text-muted-foreground">{f.issue}</p>
            </li>
          ))}
        </ul>
      )}
      {resolutions.length > 0 && (
        <ul className="space-y-1 text-xs">
          {resolutions.map((r, i) => (
            <li key={i} className="flex gap-2">
              <CheckCircle2Icon className="mt-0.5 size-3 shrink-0 text-success" />
              <span>
                <span className="font-mono text-muted-foreground">{r.action.replaceAll("_", " ")}</span> — {r.claim}
                {r.note && <span className="text-muted-foreground">: {r.note}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function SourceList({ sources }: { sources: DossierSource[] }) {
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
                <span className="min-w-0 flex-1 leading-5 break-words">
                  {s.title}
                  <ExternalLinkIcon className="ml-1 inline size-3 opacity-0 group-hover:opacity-100" />
                </span>
              </a>
              <div className="mt-1 ml-6 flex flex-wrap items-center gap-1.5">
                {s.source_type === "primary" && (
                  <Badge variant="outline" className="border-success/40 text-[10px] text-success">
                    primary
                  </Badge>
                )}
                {s.kind && <span className="text-[10px] text-muted-foreground">{s.kind}</span>}
                {s.claims_checked > 0 && (
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {s.claims_verified}/{s.claims_checked} claims verified
                  </span>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </>
  )
}
