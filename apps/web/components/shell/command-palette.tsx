"use client"

import { PanelRightIcon, PlayIcon, RefreshCwIcon } from "lucide-react"
import { useRouter } from "next/navigation"
import { toast } from "sonner"

import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command"
import { api } from "@/lib/api"
import useSWR from "swr"

import { useProposePlan } from "@/components/plans/propose-provider"
import { fetcher } from "@/lib/api"
import type { Story } from "@/lib/types"
import { AGENT_INFO, NAV } from "@/lib/nav"

export function CommandPalette({
  open,
  onOpenChange,
  onTogglePanel,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onTogglePanel: () => void
}) {
  const router = useRouter()
  const propose = useProposePlan()
  const { data: stories } = useSWR<Story[]>(open ? "/api/stories" : null, fetcher)
  const run = (fn: () => void) => {
    onOpenChange(false)
    fn()
  }

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Command palette" description="Jump to a page, start an agent, or find a story">
      <Command>
      <CommandInput placeholder="Jump to, run an agent, or search stories…" />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        <CommandGroup heading="Go to">
          {NAV.map((item) => (
            <CommandItem key={item.href} value={`go ${item.label}`} onSelect={() => run(() => router.push(item.href))}>
              <item.icon />
              {item.label}
              <CommandShortcut>g {item.key}</CommandShortcut>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Start an agent">
          {AGENT_INFO.map((agent) => (
            <CommandItem
              key={agent.name}
              value={`run ${agent.name} ${agent.description}`}
              onSelect={() =>
                run(() =>
                  agent.name === "scout"
                    ? void propose("scout", { mode: "both", limit: 25 }, "Find up to 25 story leads (news + evergreen)")
                    : agent.name === "outlier"
                      ? void propose("outlier", {}, "Scan all competitor channels for outliers")
                      : router.push(`/chat?compose=${encodeURIComponent(`@${agent.name} `)}`),
                )
              }
            >
              <PlayIcon />
              <span className="font-mono text-brand">@{agent.name}</span>
              <span className="text-muted-foreground">{agent.description}</span>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Stories">
          {(stories ?? []).slice(0, 200).map((story) => (
            <CommandItem
              key={story.id}
              value={`story ${story.id} ${story.title} ${story.company ?? ""} ${story.series ?? ""}`}
              onSelect={() => run(() => router.push(`/stories?story=${story.id}`))}
            >
              <span>{story.title}</span>
              <span className="text-muted-foreground">{story.series}</span>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Actions">
          <CommandItem value="toggle live panel" onSelect={() => run(onTogglePanel)}>
            <PanelRightIcon />
            Toggle live panel
            <CommandShortcut>⌘.</CommandShortcut>
          </CommandItem>
          <CommandItem
            value="reload env keys config"
            onSelect={() =>
              run(() =>
                toast.promise(api("/api/system/reload", { method: "POST" }), {
                  loading: "Reloading .env and config…",
                  success: "Reloaded keys and config",
                  error: (e: Error) => e.message,
                }),
              )
            }
          >
            <RefreshCwIcon />
            Reload .env and config
          </CommandItem>
        </CommandGroup>
      </CommandList>
      </Command>
    </CommandDialog>
  )
}
