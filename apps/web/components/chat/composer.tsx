"use client"

import { Loader2Icon } from "lucide-react"
import { useMemo, useRef, useState } from "react"
import useSWR from "swr"

import { Button } from "@/components/ui/button"
import { fetcher } from "@/lib/api"
import { AGENT_INFO } from "@/lib/nav"
import type { AgentSettings } from "@/lib/types"
import { cn } from "@/lib/utils"

const QUICK = ["scout", "outlier", "researcher"] as const

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
              <span className="font-mono text-sm text-brand-soft">@{agent.name}</span>
              <span className="text-xs text-muted-foreground">{agent.description}</span>
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-2.5 rounded-[18px] border border-white/10 bg-card-creative py-3 pr-3 pl-[18px] shadow-[0_0_0_4px_rgb(139_92_246/0.08)] focus-within:border-brand-soft/40">
        <label htmlFor="chat-composer" className="sr-only">
          Message
        </label>
        <textarea
          id="chat-composer"
          ref={ref}
          value={text}
          rows={2}
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
          placeholder="Ask the orchestrator, or type @ to call an agent"
          className="max-h-48 min-h-12 resize-none bg-transparent pt-1 text-[15.5px] leading-normal text-foreground-warm outline-none placeholder:text-subtle-foreground field-sizing-content"
        />
        <div className="flex flex-wrap items-center gap-1.5">
          {QUICK.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => {
                setText((t) => `@${name} ${t.replace(/^@\w+\s*/, "")}`)
                ref.current?.focus()
              }}
              className="h-9 rounded-[10px] border border-white/8 bg-[#1e212b] px-3 font-mono text-[12.5px] text-foreground-warm transition-colors hover:border-white/20"
            >
              @{name}
            </button>
          ))}
          <Button
            onClick={send}
            disabled={!text.trim() || busy || disabled}
            className="ml-auto h-11 rounded-xl bg-brand px-[18px] font-display text-[15px] font-extrabold text-brand-foreground hover:bg-brand/90"
          >
            {busy ? <Loader2Icon className="animate-spin" /> : null} Send →
          </Button>
        </div>
      </div>
      <p className="mt-1.5 px-1 text-[11.5px] text-subtle-foreground">
        @mentions skip the orchestrator and go straight to a plan card (no Claude usage). Enter sends, Shift+Enter adds a line.
      </p>
    </div>
  )
}
