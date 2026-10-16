"use client"

import { PanelLeftCloseIcon, PanelLeftOpenIcon, SearchIcon } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useMemo } from "react"
import useSWR from "swr"

import { AgentStatus, type AgentState } from "@/components/blocks/agent-status"
import { MeterBar } from "@/components/blocks/meter-bar"
import { Kbd } from "@/components/common/kbd"
import { CLAUDE_STATE_LABEL } from "@/components/settings/claude-status"
import { useStartAgent } from "@/components/shell/start-agent"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useEngineEvent, useEvents } from "@/hooks/use-events"
import { useOutliers, usePlans, useRuns, useStories, useUsage } from "@/hooks/use-live"
import { useLocalState } from "@/hooks/use-local-state"
import { fetcher } from "@/lib/api"
import { NAV } from "@/lib/nav"
import type { AgentSettings, ClaudeStatus, DossierSummary } from "@/lib/types"
import { cn } from "@/lib/utils"

const OUTLIERS_SEEN_KEY = "wyrd.outliersSeenAt"

/** Counts and badges for the nav: real data only. */
function useNavBadges() {
  const pathname = usePathname()
  const stories = useStories()
  const dossiers = useSWR<DossierSummary[]>("/api/dossiers", fetcher)
  useEngineEvent(["dossier.saved"], () => void dossiers.mutate())
  const outliers = useOutliers()
  const pending = usePlans("pending")
  const [seenAt, setSeenAt] = useLocalState<string | null>(OUTLIERS_SEEN_KEY, null)

  // Visiting Outliers marks everything scanned so far as seen.
  useEffect(() => {
    if (pathname.startsWith("/outliers") && outliers.data) {
      const latest = outliers.data.reduce<string | null>((m, v) => (v.scanned_at && (!m || v.scanned_at > m) ? v.scanned_at : m), null)
      if (latest && latest !== seenAt) setSeenAt(latest)
    }
  }, [pathname, outliers.data, seenAt, setSeenAt])

  const newOutliers = outliers.data?.filter((v) => v.scanned_at && (!seenAt || v.scanned_at > seenAt)).length ?? 0
  return {
    "/stories": stories.data ? String(stories.data.length) : null,
    "/research": dossiers.data ? String(dossiers.data.length) : null,
    "/outliers": newOutliers > 0 && !pathname.startsWith("/outliers") ? `${newOutliers} new` : null,
    chatNeedsYou: (pending.data?.length ?? 0) > 0,
  }
}

/** running (cyan) if a run is live, failed if its latest run failed, else idle. */
function useAgentStates(): Record<string, AgentState> {
  const runs = useRuns("limit=40")
  return useMemo(() => {
    const out: Record<string, AgentState> = {}
    for (const run of [...(runs.data ?? [])].reverse()) {
      // oldest → newest, so the latest run wins; any live run means running
      if (out[run.agent] === "running") continue
      out[run.agent] = run.status === "running" || run.status === "queued" ? "running" : run.status === "failed" ? "failed" : "idle"
    }
    return out
  }, [runs.data])
}

export function Sidebar({
  onOpenPalette,
  onNavigate,
  collapsed = false,
  onToggleCollapsed,
  className,
}: {
  onOpenPalette: () => void
  onNavigate?: () => void
  /** 64px icon rail (desktop only). */
  collapsed?: boolean
  onToggleCollapsed?: () => void
  className?: string
}) {
  const pathname = usePathname()
  const badges = useNavBadges()
  const states = useAgentStates()
  const startAgent = useStartAgent()
  const { data: agents } = useSWR<AgentSettings[]>("/api/agents", fetcher, { revalidateOnFocus: false })
  const visible = (agents ?? []).filter((a) => a.available && !a.hidden)

  const withTip = (label: string, node: React.ReactElement) =>
    collapsed ? (
      <Tooltip>
        <TooltipTrigger asChild>{node}</TooltipTrigger>
        <TooltipContent side="right">{label}</TooltipContent>
      </Tooltip>
    ) : (
      node
    )

  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col gap-5 overflow-y-auto border-r border-sidebar-border bg-sidebar py-5 transition-[width] duration-200",
        collapsed ? "w-16 items-center px-2.5" : "w-[232px] px-3.5",
        className,
      )}
    >
      <div className={cn("flex items-center gap-2.5", !collapsed && "px-1.5")}>
        <Link
          href="/"
          onClick={onNavigate}
          aria-label="wyrd.exe home"
          className="flex size-[30px] shrink-0 items-center justify-center rounded-lg border border-brand-soft/45 bg-[#11131b] font-mono text-[13px] font-semibold text-brand-soft shadow-[0_0_18px_rgb(139_92_246/0.35)]"
        >
          w
        </Link>
        {!collapsed && (
          <div className="flex min-w-0 flex-col">
            <span className="font-mono text-[15px] font-semibold tracking-[-0.2px]">
              wyrd<span className="text-brand-soft">.exe</span>
            </span>
            <span className="font-mono text-[10.5px] tracking-[0.6px] text-subtle-foreground">STORY ENGINE · v1</span>
          </div>
        )}
      </div>

      {withTip(
        "Search or run an agent (⌘K)",
        <button
          type="button"
          onClick={onOpenPalette}
          aria-label="Search or run an agent"
          className={cn(
            "flex h-10 shrink-0 items-center gap-2 rounded-[10px] border border-white/8 bg-[#11131b] text-[13px] text-subtle-foreground transition-colors hover:text-foreground",
            collapsed ? "w-11 justify-center" : "px-2.5",
          )}
        >
          <SearchIcon className="size-[15px]" />
          {!collapsed && (
            <>
              <span className="flex-1 text-left">Search or run…</span>
              <Kbd className="border-white/8 bg-secondary text-foreground">⌘K</Kbd>
            </>
          )}
        </button>,
      )}

      <nav className={cn("flex flex-col gap-0.5", collapsed && "items-center")} aria-label="Main">
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)
          const badge = badges[item.href as keyof typeof badges]
          return withTip(
            `${item.label} (g ${item.key})`,
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              aria-label={collapsed ? item.label : undefined}
              className={cn(
                "group relative flex h-10 items-center gap-2.5 rounded-[10px] text-sm text-[#b4b8c6] transition-colors hover:bg-white/4 hover:text-foreground",
                collapsed ? "w-11 justify-center" : "px-2.5",
                active && "bg-sidebar-accent font-medium text-sidebar-accent-foreground shadow-[inset_0_0_0_1px_rgb(167_139_250/0.3)]",
              )}
            >
              <item.icon className={cn("size-[17px] shrink-0", active && "text-brand-soft")} />
              {!collapsed && <span className="flex-1">{item.label}</span>}
              {item.href === "/chat" && badges.chatNeedsYou && (
                <span
                  aria-label="a plan is waiting for you"
                  className={cn("size-[7px] rounded-full bg-brand-soft shadow-[0_0_8px_var(--brand-soft)]", collapsed && "absolute top-2 right-2")}
                />
              )}
              {!collapsed && typeof badge === "string" &&
                (item.href === "/outliers" ? (
                  <span className="num rounded-full bg-live/12 px-[7px] py-px text-[11px] text-live-text">{badge}</span>
                ) : (
                  <span className="num text-[11.5px] text-subtle-foreground">{badge}</span>
                ))}
            </Link>,
          )
        })}
      </nav>

      {visible.length > 0 && (
        <section aria-label="Agents" className={cn("flex flex-col gap-0.5", collapsed && "items-center")}>
          {!collapsed && <h2 className="px-2.5 pb-1.5 font-mono text-[10.5px] tracking-[1px] text-subtle-foreground">AGENTS</h2>}
          {visible.map((agent) =>
            withTip(
              `@${agent.name}: ${states[agent.name] ?? "idle"} · click to start a run`,
              <button
                key={agent.name}
                type="button"
                onClick={() => {
                  onNavigate?.()
                  startAgent(agent.name)
                }}
                className={cn(
                  "flex h-9 items-center gap-2.5 rounded-[10px] text-left transition-colors hover:bg-white/4",
                  collapsed ? "w-11 justify-center" : "px-2.5",
                )}
              >
                {collapsed ? (
                  <AgentStatus state={states[agent.name] ?? "idle"} label="" />
                ) : (
                  <>
                    <span className={cn("flex-1 font-mono text-[13px]", states[agent.name] === "running" ? "text-live-text" : "text-foreground")}>
                      @{agent.name}
                    </span>
                    <AgentStatus state={states[agent.name] ?? "idle"} />
                  </>
                )}
              </button>,
            ),
          )}
        </section>
      )}

      <div className={cn("mt-auto flex flex-col gap-2", collapsed && "items-center")}>
        <ClaudeFooter collapsed={collapsed} />
        {onToggleCollapsed &&
          withTip(
            collapsed ? "Expand sidebar (⌘\\)" : "Collapse sidebar (⌘\\)",
            <button
              type="button"
              onClick={onToggleCollapsed}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className={cn(
                "flex h-9 items-center gap-2 rounded-[10px] text-xs text-subtle-foreground transition-colors hover:bg-white/4 hover:text-foreground",
                collapsed ? "w-11 justify-center" : "px-2.5",
              )}
            >
              {collapsed ? <PanelLeftOpenIcon className="size-4" /> : <PanelLeftCloseIcon className="size-4" />}
              {!collapsed && "Collapse"}
            </button>,
          )}
      </div>
    </aside>
  )
}

/** Claude CLI status + today's Claude runs vs. the soft cap, and the engine connection. */
function ClaudeFooter({ collapsed }: { collapsed: boolean }) {
  const { status } = useEvents()
  const health = useSWR<{ claude: ClaudeStatus | null }>("/api/health", fetcher, { refreshInterval: 60_000 })
  const usage = useUsage()
  const claude = health.data?.claude
  const meter = usage.data?.meters.find((m) => m.provider === "claude")?.claude
  const engine = status === "open" ? "connected" : status === "connecting" ? "connecting…" : "offline"
  const state: AgentState = !claude ? "idle" : claude.state === "ready" ? "ready" : claude.state === "unknown" ? "idle" : "failed"

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Link href="/settings?tab=agents" aria-label="Claude CLI status" className="flex size-11 items-center justify-center rounded-[10px] hover:bg-white/4">
            <AgentStatus state={state} label="" />
          </Link>
        </TooltipTrigger>
        <TooltipContent side="right">
          Claude CLI: {claude ? CLAUDE_STATE_LABEL[claude.state] : "checking…"} · engine {engine}
        </TooltipContent>
      </Tooltip>
    )
  }
  return (
    <Link
      href="/settings?tab=agents"
      className="flex flex-col gap-2.5 rounded-xl border border-white/6 bg-[#0e1017] p-3 transition-colors hover:border-white/12"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12.5px] font-medium">Claude CLI</span>
        <AgentStatus state={state} label={claude ? CLAUDE_STATE_LABEL[claude.state] : "checking…"} />
      </div>
      {claude?.version && <span className="num -mt-1.5 text-[11px] text-subtle-foreground">{claude.version.replace(" (Claude Code)", "")}</span>}
      {meter && <MeterBar label={<span className="text-xs text-muted-foreground">Claude runs today</span>} used={meter.chat_turns + meter.agent_runs} limit={meter.soft_cap} />}
      <span className="flex items-center gap-1.5 text-[11px] text-subtle-foreground">
        <span className={cn("size-1.5 rounded-full", status === "open" ? "bg-success" : status === "connecting" ? "bg-warning" : "bg-destructive")} />
        Engine {engine}
      </span>
    </Link>
  )
}
