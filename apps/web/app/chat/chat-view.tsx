"use client"

import { ArrowRightIcon, BotIcon, MessageSquarePlusIcon, MessagesSquareIcon } from "lucide-react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import { toast } from "sonner"

import { AgentTag } from "@/components/common/badges"
import { SampleBadge } from "@/components/common/page-header"
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Composer } from "@/components/chat/composer"
import { PlanCard } from "@/components/chat/plan-card"
import { Button } from "@/components/ui/button"
import { useDemo } from "@/hooks/use-demo"
import { timeAgo } from "@/lib/format"
import { MOCK_THREADS } from "@/lib/mock"
import type { ChatMessage, ChatThread } from "@/lib/types"
import { cn } from "@/lib/utils"

export function ChatView() {
  const compose = useSearchParams().get("compose") ?? ""
  const { data, isLoading, error, retry } = useDemo(MOCK_THREADS, [])
  // Local edits (sent messages, new chats) layered over the loaded threads.
  const [edited, setThreads] = useState<ChatThread[] | null>(null)
  const threads = edited ?? data ?? []
  const [chosenId, setActiveId] = useState<number | null>(null)
  const activeId = chosenId ?? threads[0]?.id ?? null
  const bottomRef = useRef<HTMLDivElement>(null)

  const active = threads.find((t) => t.id === activeId)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [active?.messages.length])

  const send = (text: string) => {
    if (!active) return
    const message: ChatMessage = { id: Date.now(), role: "user", content: text, created_at: new Date().toISOString() }
    setThreads(threads.map((t) => (t.id === active.id ? { ...t, messages: [...t.messages, message] } : t)))
    toast.info("The orchestrator is connected in Phase 5. Your message is shown locally only.")
  }

  const newChat = () => {
    const thread: ChatThread = { id: Date.now(), title: "New chat", updated_at: new Date().toISOString(), messages: [] }
    setThreads([thread, ...threads])
    setActiveId(thread.id)
  }

  return (
    <div className="flex h-full">
      <div className="flex w-64 shrink-0 flex-col border-r">
        <div className="flex h-14 items-center justify-between px-4">
          <span className="flex items-center gap-2 text-sm font-medium">Chats <SampleBadge /></span>
          <Button variant="ghost" size="icon-sm" onClick={newChat} aria-label="New chat">
            <MessageSquarePlusIcon />
          </Button>
        </div>
        <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {isLoading ? (
            <LoadingState rows={4} className="px-2" />
          ) : error ? null : threads.length === 0 ? (
            <p className="px-2 py-4 text-xs text-muted-foreground">No chats yet.</p>
          ) : (
            threads.map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveId(t.id)}
                className={cn(
                  "w-full rounded-md px-2.5 py-2 text-left transition-colors hover:bg-muted",
                  t.id === activeId && "bg-muted",
                )}
              >
                <p className="truncate text-sm">{t.title}</p>
                <p className="text-[11px] text-muted-foreground">{timeAgo(t.updated_at)}</p>
              </button>
            ))
          )}
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-6 py-8">
            {isLoading ? (
              <LoadingState rows={3} />
            ) : error ? (
              <ErrorState error={error} onRetry={retry} />
            ) : !active ? (
              <EmptyState
                icon={MessagesSquareIcon}
                title="Start a conversation"
                description='Ask the orchestrator for work ("find me 10 fraud stories") or type @scout, @outlier, or @researcher.'
                action={<Button size="sm" onClick={newChat}><MessageSquarePlusIcon /> New chat</Button>}
              />
            ) : active.messages.length === 0 ? (
              <EmptyState
                icon={BotIcon}
                title="New chat"
                description="Try: “What stories do we have in Fraud Files?” or “@scout mode=news topic=restaurants”."
              />
            ) : (
              <div className="space-y-6">
                {active.messages.map((m) => (
                  <Message key={m.id} message={m} />
                ))}
                <div ref={bottomRef} />
              </div>
            )}
          </div>
        </div>
        <div className="mx-auto w-full max-w-3xl px-6 pb-6">
          <Composer key={compose} initial={compose} onSend={send} />
        </div>
      </div>
    </div>
  )
}

function Message({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-secondary px-4 py-2.5 text-sm whitespace-pre-wrap">
          {message.content.split(/(@\w+)/).map((part, i) =>
            part.startsWith("@") ? <span key={i} className="font-mono text-brand">{part}</span> : part,
          )}
        </div>
      </div>
    )
  }
  if (message.result) {
    const r = message.result
    return (
      <Link href={r.href} className="block rounded-lg border bg-card p-4 transition-colors hover:border-brand/40">
        <div className="flex items-center gap-2">
          <AgentTag agent={r.agent} />
          <span className="text-sm font-medium">{r.headline}</span>
          <ArrowRightIcon className="ml-auto size-3.5 text-muted-foreground" />
        </div>
        <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
          {r.items.map((item) => <li key={item}>· {item}</li>)}
        </ul>
        <p className="mt-2 font-mono text-[10px] text-muted-foreground/70">run #{r.run_id}</p>
      </Link>
    )
  }
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-brand-muted">
        <BotIcon className="size-3.5 text-brand" />
      </div>
      <div className="min-w-0 flex-1 text-sm leading-6 [&_strong]:font-semibold">
        <ReactMarkdown>{message.content}</ReactMarkdown>
        {message.plan && <PlanCard plan={message.plan} />}
      </div>
    </div>
  )
}
