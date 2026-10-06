"use client"

import { ArrowUpIcon, Loader2Icon } from "lucide-react"
import { useMemo, useRef, useState } from "react"
import useSWR from "swr"

import { Button } from "@/components/ui/button"
import { fetcher } from "@/lib/api"
import { AGENT_INFO } from "@/lib/nav"
import type { AgentSettings } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Chat input with @-autocomplete for agents (descriptions from /api/agents).
 *  Enter sends, Shift+Enter adds a line. */
export function Composer({
  initial = "",
  onSend,
  busy = false,
  disabled = false,
}: {
  initial?: string
  onSend: (text: string) => void | Promise<void>
  busy?: boolean
  disabled?: boolean
}) {
  const { data: agents } = useSWR<AgentSettings[]>("/api/agents", fetcher, { revalidateOnFocus: false })
  const options = useMemo(
    () =>
      agents
        ? agents
            .filter((a) => a.available && !a.hidden)
            .map((a) => ({
              name: a.name,
              description: a.implemented === false ? `${a.description} (${a.arrives_in ?? "coming"})` : a.description,
            }))
        : AGENT_INFO.map((a) => ({ name: a.name, description: a.description })),
    [agents],
  )
  const [text, setText] = useState(initial)
  const [active, setActive] = useState(0)
  const ref = useRef<HTMLTextAreaElement>(null)

  const mention = /(^|\s)@(\w*)$/.exec(text)
  const matches = useMemo(
    () => (mention ? options.filter((a) => a.name.startsWith(mention[2].toLowerCase())) : []),
    [mention, options],
  )
  const open = matches.length > 0

  const complete = (name: string) => {
    setText(text.replace(/@(\w*)$/, `@${name} `))
    setActive(0)
    ref.current?.focus()
  }

  const send = () => {
    if (!text.trim() || busy || disabled) return
    void onSend(text.trim())
    setText("")
  }

  return (
    <div className="relative">
      {open && (
        <div role="listbox" className="absolute bottom-full left-0 mb-2 w-80 max-w-full overflow-hidden rounded-lg border bg-popover p-1 shadow-lg">
          {matches.map((agent, i) => (
            <button
              key={agent.name}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault()
                complete(agent.name)
              }}
              className={cn("flex w-full flex-col rounded-md px-2.5 py-1.5 text-left", i === active && "bg-accent")}
            >
              <span className="font-mono text-sm text-brand">@{agent.name}</span>
              <span className="text-xs text-muted-foreground">{agent.description}</span>
            </button>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2 rounded-xl border bg-card p-2 focus-within:border-brand/50">
        <textarea
          ref={ref}
          value={text}
          rows={1}
          autoFocus={!!initial}
          onChange={(e) => {
            setText(e.target.value)
            setActive(0)
          }}
          onKeyDown={(e) => {
            if (open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
              e.preventDefault()
              setActive((a) => (a + (e.key === "ArrowDown" ? 1 : matches.length - 1)) % matches.length)
            } else if (open && (e.key === "Tab" || e.key === "Enter")) {
              e.preventDefault()
              complete(matches[active].name)
            } else if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          placeholder="Ask the orchestrator, or type @ to run an agent directly…"
          className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground field-sizing-content"
        />
        <Button
          size="icon-sm"
          onClick={send}
          disabled={!text.trim() || busy || disabled}
          aria-label="Send"
          className="bg-brand text-brand-foreground hover:bg-brand/90"
        >
          {busy ? <Loader2Icon className="animate-spin" /> : <ArrowUpIcon />}
        </Button>
      </div>
      <p className="mt-1.5 px-1 text-[11px] text-muted-foreground">
        @mentions skip the orchestrator and go straight to a plan card (saves Claude usage).
      </p>
    </div>
  )
}
