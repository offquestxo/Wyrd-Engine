"use client"

import useSWR from "swr"

import { ErrorState, LoadingState } from "@/components/common/states"
import { ConfigEditor } from "@/components/settings/config-editor"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { fetcher } from "@/lib/api"
import { formatNumber } from "@/lib/format"
import type { ConfigFile, ProviderSummary } from "@/lib/types"
import { cn } from "@/lib/utils"

type Route = { provider: string; model: string }

export function ProvidersCard() {
  const providers = useSWR<ProviderSummary[]>("/api/providers", fetcher)
  const config = useSWR<ConfigFile>("/api/config/providers", fetcher)

  if (providers.isLoading || config.isLoading) return <LoadingState rows={8} />
  if (providers.error || config.error)
    return <ErrorState error={(providers.error ?? config.error) as Error} onRetry={() => { void providers.mutate(); void config.mutate() }} />

  const tasks = (config.data?.data.tasks ?? {}) as Record<string, Route[]>
  const modelId = (r: Route) => providers.data?.find((p) => p.provider === r.provider)?.models[r.model] ?? r.model
  const disabled = new Set(providers.data?.filter((p) => p.status === "disabled").map((p) => p.provider))
  const lim = (n: number | null) => (n === null ? "—" : formatNumber(n))

  return (
    <div className="space-y-8">
      <section>
        <h3 className="mb-2 text-sm font-medium">Task routing</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          First provider is primary; the rest are fallbacks. Providers without a key, whose key was just rejected, or that are disabled in providers.yaml are skipped.
        </p>
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Task</TableHead>
                <TableHead>Route</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(tasks).map(([task, route]) => (
                <TableRow key={task}>
                  <TableCell className="font-mono text-xs">{task}</TableCell>
                  <TableCell className="text-xs">
                    {route.map((r, i) => (
                      <span key={i} className={disabled.has(r.provider) ? "opacity-50" : undefined} title={disabled.has(r.provider) ? "disabled in providers.yaml" : undefined}>
                        {i > 0 && <span className="px-1.5 text-muted-foreground">→</span>}
                        <span className={cn(i === 0 ? "text-foreground" : "text-muted-foreground", disabled.has(r.provider) && "line-through")}>{r.provider}</span>
                        <span className="font-mono text-[10px] text-muted-foreground"> {disabled.has(r.provider) ? "disabled" : modelId(r)}</span>
                      </span>
                    ))}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-sm font-medium">Models and free-tier limits</h3>
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Provider</TableHead>
                <TableHead>Alias</TableHead>
                <TableHead>Model ID</TableHead>
                <TableHead className="text-right">RPM</TableHead>
                <TableHead className="text-right">TPM</TableHead>
                <TableHead className="text-right">RPD</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {providers.data?.flatMap((p) =>
                Object.keys(p.models).length
                  ? Object.entries(p.models).map(([alias, id]) => (
                      <TableRow key={`${p.provider}.${alias}`}>
                        <TableCell className="text-xs">{p.provider}</TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">{alias}</TableCell>
                        <TableCell className="font-mono text-xs">{id}</TableCell>
                        <TableCell className="text-right font-mono text-xs">{lim(p.model_limits[alias].rpm)}</TableCell>
                        <TableCell className="text-right font-mono text-xs">{lim(p.model_limits[alias].tpm)}</TableCell>
                        <TableCell className="text-right font-mono text-xs">{lim(p.model_limits[alias].rpd)}</TableCell>
                      </TableRow>
                    ))
                  : [
                      <TableRow key={p.provider}>
                        <TableCell className="text-xs">{p.provider}</TableCell>
                        <TableCell colSpan={5} className="font-mono text-xs text-muted-foreground">
                          {Object.entries(p.limits).map(([k, v]) => `${k}: ${v === null ? "—" : v.toLocaleString()}`).join(" · ")}
                        </TableCell>
                      </TableRow>,
                    ],
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-medium">Edit providers.yaml</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Model IDs, limits, routes, and the near-limit ratio. The Claude soft cap is on the Agents tab.
          Saving reloads the router.
        </p>
        <ConfigEditor name="providers" />
      </section>
    </div>
  )
}
