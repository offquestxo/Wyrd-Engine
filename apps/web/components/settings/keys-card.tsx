"use client"

import { KeyRoundIcon, Loader2Icon, PlugIcon, RefreshCwIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, fetcher } from "@/lib/api"
import type { ConnectionTest, KeyStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

const STATUS_STYLE: Record<KeyStatus["status"], string> = {
  set: "border-success/40 text-success",
  missing: "border-border text-muted-foreground",
  failing: "border-destructive/40 text-destructive",
}

export function KeysCard() {
  const { data, error, isLoading, mutate } = useSWR<KeyStatus[]>("/api/keys", fetcher)
  const [testing, setTesting] = useState<string | null>(null)

  const test = async (provider: string) => {
    setTesting(provider)
    try {
      const result = await api<ConnectionTest>(`/api/providers/${provider}/test`, { method: "POST" })
      if (result.ok) toast.success(`${provider}: ${result.detail}`, { description: `${result.latency_ms} ms` })
      else toast.error(`${provider} failed`, { description: result.detail })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setTesting(null)
      await mutate()
    }
  }

  const reload = async () => {
    try {
      await api("/api/system/reload", { method: "POST" })
      toast.success("Reloaded .env and config")
      await mutate()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (isLoading) return <LoadingState rows={8} />
  if (error) return <ErrorState error={error as Error} onRetry={() => mutate()} />
  if (!data?.length) return <EmptyState icon={KeyRoundIcon} title="No keys configured" />

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Keys are read from <code className="font-mono text-xs">.env</code> and never shown in full. Edit the file, then reload.
        </p>
        <Button size="sm" variant="outline" onClick={reload}><RefreshCwIcon /> Reload .env</Button>
      </div>
      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Key</TableHead>
              <TableHead>Used for</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Value</TableHead>
              <TableHead className="text-right">Connection</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((k) => (
              <TableRow key={k.env}>
                <TableCell className="font-mono text-xs">{k.env}</TableCell>
                <TableCell className="max-w-xs text-xs whitespace-normal text-muted-foreground">
                  {k.purpose}
                  {k.note && <p className="mt-1 text-[11px] leading-4 text-warning">{k.note}</p>}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={cn("font-mono text-[10px] uppercase", STATUS_STYLE[k.status])}>
                    {k.status}
                  </Badge>
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{k.preview || "—"}</TableCell>
                <TableCell className="w-72 text-right whitespace-normal">
                  {k.testable && k.provider && (
                    <div className="flex flex-col items-end gap-1">
                      <Button size="xs" variant="outline" disabled={k.status === "missing" || testing !== null} onClick={() => test(k.provider!)}>
                        {testing === k.provider ? <Loader2Icon className="animate-spin" /> : <PlugIcon />} Test connection
                      </Button>
                      {k.last_test && (
                        <p className={cn("line-clamp-3 max-w-72 text-left text-[11px] leading-4", k.last_test.ok ? "text-success" : "text-destructive")} title={k.last_test.detail}>
                          {k.last_test.ok ? `OK · ${k.last_test.latency_ms} ms` : k.last_test.detail}
                          {k.last_test.auth && <span className="text-muted-foreground"> · via {k.last_test.auth}</span>}
                        </p>
                      )}
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
