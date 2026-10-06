"use client"

import { ArrowLeftIcon, Loader2Icon, SearchXIcon, SquareIcon } from "lucide-react"
import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { AgentTag, RunStatusBadge } from "@/components/common/badges"
import { PageHeader } from "@/components/common/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useRun } from "@/hooks/use-live"
import { useNow } from "@/hooks/use-now"
import { ApiError, api } from "@/lib/api"
import { clock, duration } from "@/lib/format"
import type { RunRecord } from "@/lib/types"
import { cn } from "@/lib/utils"

export function RunView({ id }: { id: number }) {
  const { data: run, isLoading, error, mutate } = useRun(id)
  const [cancelling, setCancelling] = useState(false)
  const now = useNow()
  const bottomRef = useRef<HTMLDivElement>(null)
  const active = run?.status === "running" || run?.status === "queued"

  useEffect(() => {
    if (active) bottomRef.current?.scrollIntoView({ block: "nearest" })
  }, [run?.logs?.length, active])

  const cancel = async () => {
    setCancelling(true)
    try {
      await api<RunRecord>(`/api/runs/${id}/cancel`, { method: "POST" })
      await mutate() // refetch: the cancel response has no log lines
      toast.success(`Run #${id} cancelled`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setCancelling(false)
    }
  }

  const notFound = error instanceof ApiError && error.status === 404

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <Link href="/" className="mb-4 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeftIcon className="size-3" /> Home
      </Link>
      {isLoading ? (
        <LoadingState rows={6} />
      ) : notFound ? (
        <EmptyState icon={SearchXIcon} title={`Run #${id} not found`} description="It may have been deleted, or the id is wrong." />
      ) : error ? (
        <ErrorState error={error as Error} onRetry={() => void mutate()} />
      ) : !run ? null : (
        <>
          <PageHeader
            title={`Run #${run.id}`}
            description={run.current_step ?? undefined}
            actions={
              active && (
                <Button variant="destructive" size="sm" onClick={() => void cancel()} disabled={cancelling}>
                  {cancelling ? <Loader2Icon className="animate-spin" /> : <SquareIcon />} Cancel run
                </Button>
              )
            }
          />
          <div className="grid gap-4 md:grid-cols-[260px_1fr]">
            <Card className="h-fit gap-3 py-4">
              <CardContent className="space-y-3 px-4 text-sm">
                <Field label="Agent"><AgentTag agent={run.agent} /></Field>
                <Field label="Status"><RunStatusBadge status={run.status} /></Field>
                {run.progress !== null && (
                  <Field label="Progress">
                    <div className="flex items-center gap-2">
                      <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
                        <div className="h-full bg-brand transition-all" style={{ width: `${run.progress * 100}%` }} />
                      </div>
                      <span className="font-mono text-xs">{Math.round(run.progress * 100)}%</span>
                    </div>
                  </Field>
                )}
                <Field label="Elapsed">
                  <span className="font-mono text-xs">
                    {run.started_at ? duration(run.started_at, run.finished_at, now) : "waiting in queue"}
                  </span>
                </Field>
                {run.plan_id && (
                  <Field label="Plan"><span className="font-mono text-xs">#{run.plan_id}</span></Field>
                )}
                <Field label="Params">
                  <pre className="overflow-x-auto rounded bg-muted p-2 font-mono text-[11px]">
                    {JSON.stringify(run.params ?? {}, null, 2)}
                  </pre>
                </Field>
                {(run.result || run.error) && (
                  <Field label={run.error ? "Error" : "Result"}>
                    {run.error ? (
                      <span className="text-xs text-destructive">{run.error}</span>
                    ) : (
                      <pre className="overflow-x-auto rounded bg-muted p-2 font-mono text-[11px]">
                        {JSON.stringify(run.result, null, 2)}
                      </pre>
                    )}
                  </Field>
                )}
              </CardContent>
            </Card>
            <Card className="gap-0 py-0">
              <CardHeader className="flex flex-row items-center justify-between border-b px-4 py-3">
                <CardTitle className="text-sm">Log</CardTitle>
                {active && (
                  <span className="flex items-center gap-1.5 text-[11px] text-brand">
                    <span className="size-1.5 animate-pulse rounded-full bg-brand" /> live
                  </span>
                )}
              </CardHeader>
              <CardContent className="max-h-[70vh] space-y-1 overflow-y-auto px-4 py-3 font-mono text-xs leading-6">
                {(run.logs ?? []).length === 0 && <p className="text-muted-foreground">No log lines yet.</p>}
                {(run.logs ?? []).map((log) => (
                  <div key={log.id} className="flex gap-3">
                    <span className="shrink-0 text-muted-foreground/60">{clock(log.ts)}</span>
                    <span
                      className={cn(
                        "w-10 shrink-0 uppercase",
                        log.level === "error" ? "text-destructive" : log.level === "warn" ? "text-warning" : "text-muted-foreground",
                      )}
                    >
                      {log.level}
                    </span>
                    <span className="flex-1 break-words">{log.message}</span>
                  </div>
                ))}
                {active && <div className="h-4 w-2 animate-pulse bg-brand/70" />}
                <div ref={bottomRef} />
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-[11px] tracking-wide text-muted-foreground uppercase">{label}</p>
      {children}
    </div>
  )
}
