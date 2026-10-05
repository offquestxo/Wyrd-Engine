"use client"

import { ArrowLeftIcon, SearchXIcon, SquareIcon } from "lucide-react"
import Link from "next/link"
import { toast } from "sonner"

import { AgentTag, RunStatusBadge } from "@/components/common/badges"
import { PageHeader } from "@/components/common/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useDemo } from "@/hooks/use-demo"
import { clock, duration } from "@/lib/format"
import { MOCK_RUNS } from "@/lib/mock"
import { cn } from "@/lib/utils"

export function RunView({ id }: { id: number }) {
  const { data, isLoading, error, retry } = useDemo(MOCK_RUNS, [])
  const run = data?.find((r) => r.id === id)

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <Link href="/" className="mb-4 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeftIcon className="size-3" /> Home
      </Link>
      {isLoading ? (
        <LoadingState rows={6} />
      ) : error ? (
        <ErrorState error={error} onRetry={retry} />
      ) : !run ? (
        <EmptyState icon={SearchXIcon} title={`Run #${id} not found`} description="It may have been deleted, or the id is wrong." />
      ) : (
        <>
          <PageHeader
            title={`Run #${run.id}`}
            sample
            actions={
              run.status === "running" && (
                <Button variant="destructive" size="sm" onClick={() => toast.info("Cancellation is wired up in Phase 2.")}>
                  <SquareIcon /> Cancel run
                </Button>
              )
            }
          />
          <div className="grid gap-4 md:grid-cols-[260px_1fr]">
            <Card className="h-fit gap-3 py-4">
              <CardContent className="space-y-3 px-4 text-sm">
                <Field label="Agent"><AgentTag agent={run.agent} /></Field>
                <Field label="Status"><RunStatusBadge status={run.status} /></Field>
                <Field label="Elapsed">
                  <span className="font-mono text-xs">{run.started_at ? duration(run.started_at, run.finished_at) : "—"}</span>
                </Field>
                <Field label="Providers">
                  <span className="font-mono text-xs">{run.providers.join(", ")}</span>
                </Field>
                <Field label="Params">
                  <pre className="overflow-x-auto rounded bg-muted p-2 font-mono text-[11px]">{JSON.stringify(run.params, null, 2)}</pre>
                </Field>
                {(run.summary || run.error) && (
                  <Field label={run.error ? "Error" : "Result"}>
                    <span className={cn("text-xs", run.error && "text-destructive")}>{run.error ?? run.summary}</span>
                  </Field>
                )}
              </CardContent>
            </Card>
            <Card className="gap-0 py-0">
              <CardHeader className="border-b px-4 py-3">
                <CardTitle className="text-sm">Log</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 px-4 py-3 font-mono text-xs leading-6">
                {run.logs.map((log, i) => (
                  <div key={i} className="flex gap-3">
                    <span className="text-muted-foreground/60">{clock(log.ts)}</span>
                    <span className={cn("w-10 uppercase", log.level === "error" ? "text-destructive" : log.level === "warn" ? "text-warning" : "text-muted-foreground")}>
                      {log.level}
                    </span>
                    <span className="flex-1">{log.message}</span>
                  </div>
                ))}
                {run.status === "running" && <div className="h-4 w-2 animate-pulse bg-brand/70" />}
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
