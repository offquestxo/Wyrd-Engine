"use client"

import {
  AlertTriangleIcon,
  BotIcon,
  InfoIcon,
  Loader2Icon,
  MenuIcon,
  MessageSquarePlusIcon,
  MessagesSquareIcon,
  SparklesIcon,
  Trash2Icon,
  WrenchIcon,
  ZapIcon,
} from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import useSWR from "swr"
import { toast } from "sonner"

import { EmptyState, ErrorState, LoadingState } from "@/components/common/states"
import { Composer } from "@/components/chat/composer"
import { ResultCard } from "@/components/chat/result-card"
import { LivePlanCard } from "@/components/plans/live-plan-card"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { useChat, useChats } from "@/hooks/use-chat"
import { useUsage } from "@/hooks/use-live"
import { api, fetcher } from "@/lib/api"
import { timeAgo } from "@/lib/format"
import type { ChatDetail, ChatMessageRecord, ChatSummary, ClaudeStatus, PlanRecord } from "@/lib/types"
import { cn } from "@/lib/utils"

export function ChatView() {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const compose = params.get("compose") ?? ""
  const chats = useChats()
  const selected = Number(params.get("chat")) || null
  const activeId = selected ?? chats.data?.[0]?.id ?? null
  const chat = useChat(activeId)
  const [threadsOpen, setThreadsOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const health = useSWR<{ claude: ClaudeStatus | null }>("/api/health", fetcher, { refreshInterval: 60_000 })
  const claude = health.data?.claude
  const claudeReady = !claude || (claude.installed && claude.logged_in)

  const select = (id: number | null) => {
    const next = new URLSearchParams(params.toString())
    if (id) next.set("chat", String(id))
    else next.delete("chat")
    next.delete("compose")
    router.replace(`${pathname}?${next.toString()}`)
    setThreadsOpen(false)
  }

  const messages = chat.data?.messages ?? []
  const streamLength = Object.values(chat.streams).reduce((n, s) => n + s.length, 0)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [messages.length, streamLength, activeId])

  const newChat = async () => {
    try {
      const created = await api<ChatSummary>("/api/chats", { method: "POST", body: "{}" })
      await chats.mutate()
      select(created.id)
      return created.id
    } catch (e) {
      toast.error((e as Error).message)
      return null
    }
  }

  const send = async (text: string) => {
    setSending(true)
    try {
      const id = activeId ?? (await newChat())
      if (!id) return
      const message = await api<ChatMessageRecord>(`/api/chats/${id}/messages`, {
        method: "POST",
        body: JSON.stringify({ content: text }),
      })
      if (id === activeId && chat.data)
        await chat.mutate(
          (c) => c && { ...c, messages: c.messages.some((m) => m.id === message.id) ? c.messages : [...c.messages, message] },
          { revalidate: false },
        )
      if (activeId !== id) select(id)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSending(false)
    }
  }

  const remove = async (id: number) => {
    if (!window.confirm("Delete this chat? Its plans and runs stay in history.")) return
    try {
      await api(`/api/chats/${id}`, { method: "DELETE" })
      await chats.mutate()
      if (id === activeId) select(null)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const threadList = (
    <ThreadList
      chats={chats.data}
      loading={chats.isLoading}
      error={chats.error as Error | undefined}
      activeId={activeId}
      onSelect={select}
      onNew={() => void newChat()}
      onRetry={() => void chats.mutate()}
    />
  )

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 flex-col border-r md:flex">{threadList}</aside>
      <Sheet open={threadsOpen} onOpenChange={setThreadsOpen}>
        <SheetContent side="left" className="w-72 p-0">
          <SheetTitle className="sr-only">Chats</SheetTitle>
          <div className="flex h-full flex-col">{threadList}</div>
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4 sm:px-6">
          <Button variant="ghost" size="icon-sm" className="md:hidden" onClick={() => setThreadsOpen(true)} aria-label="Chats">
            <MenuIcon />
          </Button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium">{chat.data?.title ?? "Chat"}</h1>
          <ClaudeMeterChip />
          {chat.data && (
            <Button variant="ghost" size="icon-sm" onClick={() => void remove(chat.data!.id)} aria-label="Delete chat" disabled={chat.data.busy}>
              <Trash2Icon />
            </Button>
          )}
        </header>

        {!claudeReady && claude && (
          <div role="status" className="flex items-start gap-2 border-b border-warning/20 bg-warning/5 px-4 py-2 text-xs sm:px-6">
            <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0 text-warning" />
            <span className="text-foreground/80">
              The orchestrator is unavailable: {claude.detail} You can still use <span className="font-mono">@scout</span> and{" "}
              <span className="font-mono">@outlier</span> mentions; they don&apos;t need Claude.
            </span>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
            {chats.isLoading || (activeId && chat.isLoading) ? (
              <LoadingState rows={3} />
            ) : chats.error ? (
              <ErrorState error={chats.error as Error} onRetry={() => void chats.mutate()} />
            ) : chat.error ? (
              <ErrorState error={chat.error as Error} onRetry={() => void chat.mutate()} />
            ) : !activeId ? (
              <EmptyState
                icon={MessagesSquareIcon}
                title="Start a conversation"
                description='Ask the orchestrator for work ("find me 10 fraud stories") or type @scout or @outlier to skip it.'
                action={
                  <Button size="sm" onClick={() => void newChat()}>
                    <MessageSquarePlusIcon /> New chat
                  </Button>
                }
              />
            ) : messages.length === 0 ? (
              <EmptyState
                icon={BotIcon}
                title="New chat"
                description="Try “What stories do we have in Fraud Files?” or “@scout 10 news stories about restaurant chains”."
              />
            ) : (
              <div className="space-y-5">
                {messages.map((m) => (
                  <Message key={m.id} message={m} chat={chat.data!} stream={chat.streams[m.id]} activity={chat.activity} />
                ))}
                {chat.data?.busy && !messages.some((m) => m.metadata.streaming) && (
                  <p className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2Icon className="size-3 animate-spin" /> Reading the request…
                  </p>
                )}
                <div ref={bottomRef} />
              </div>
            )}
          </div>
        </div>
        <div className="mx-auto w-full max-w-3xl px-4 pb-4 sm:px-6 sm:pb-6">
          <Composer key={compose} initial={compose} onSend={send} busy={sending || Boolean(chat.data?.busy)} />
        </div>
      </div>
    </div>
  )
}

function ThreadList({
  chats,
  loading,
  error,
  activeId,
  onSelect,
  onNew,
  onRetry,
}: {
  chats: ChatSummary[] | undefined
  loading: boolean
  error: Error | undefined
  activeId: number | null
  onSelect: (id: number) => void
  onNew: () => void
  onRetry: () => void
}) {
  return (
    <>
      <div className="flex h-14 shrink-0 items-center justify-between px-4">
        <span className="text-sm font-medium">Chats</span>
        <Button variant="ghost" size="icon-sm" onClick={onNew} aria-label="New chat">
          <MessageSquarePlusIcon />
        </Button>
      </div>
      <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {loading ? (
          <LoadingState rows={4} className="px-2" />
        ) : error ? (
          <div className="px-2 py-4 text-xs text-destructive">
            Couldn&apos;t load chats.{" "}
            <button className="underline" onClick={onRetry}>
              Retry
            </button>
          </div>
        ) : !chats?.length ? (
          <p className="px-2 py-4 text-xs text-muted-foreground">No chats yet.</p>
        ) : (
          chats.map((t) => (
            <button
              key={t.id}
              onClick={() => onSelect(t.id)}
              className={cn(
                "w-full rounded-md px-2.5 py-2 text-left transition-colors hover:bg-muted",
                t.id === activeId && "bg-muted",
              )}
            >
              <p className="flex items-center gap-1.5 truncate text-sm">
                {t.busy && <Loader2Icon className="size-3 shrink-0 animate-spin text-brand" />}
                <span className="truncate">{t.title}</span>
              </p>
              <p className="text-[11px] text-muted-foreground">{timeAgo(t.updated_at)}</p>
            </button>
          ))
        )}
      </div>
    </>
  )
}

/** Today's Claude calls vs. the soft cap (Settings), amber near the cap. */
function ClaudeMeterChip() {
  const { data } = useUsage()
  const meter = data?.meters.find((m) => m.provider === "claude")
  if (!meter?.claude) return null
  const c = meter.claude
  const limited = c.rate_limit?.status && c.rate_limit.status !== "allowed"
  return (
    <span
      title={`Claude today: ${c.chat_turns} chat turns + ${c.agent_runs} agent runs, ${c.turns} model turns, ${c.duration_s}s. Soft cap ${c.soft_cap} (Settings).${
        c.rate_limit?.status ? ` Claude Code reports: ${c.rate_limit.status}.` : ""
      }`}
      className={cn(
        "flex shrink-0 items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px]",
        c.over || limited ? "border-destructive/40 text-destructive" : c.warn ? "border-warning/40 text-warning" : "text-muted-foreground",
      )}
    >
      <SparklesIcon className="size-3" />
      {meter.used}/{c.soft_cap}
      {(c.warn || c.over) && <span className="hidden sm:inline">{c.over ? " · over cap" : " · near cap"}</span>}
    </span>
  )
}

function Message({
  message,
  chat,
  stream,
  activity,
}: {
  message: ChatMessageRecord
  chat: ChatDetail
  stream: string | undefined
  activity: string | null
}) {
  const meta = message.metadata
  if (message.role === "user") {
    return (
      <div className="flex flex-col items-end gap-1">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-secondary px-4 py-2.5 text-sm whitespace-pre-wrap">
          {message.content.split(/(@\w+)/).map((part, i) =>
            part.startsWith("@") ? (
              <span key={i} className="font-mono text-brand">
                {part}
              </span>
            ) : (
              part
            ),
          )}
        </div>
        {meta.fast_path && (
          <span className="flex items-center gap-1 text-[11px] text-muted-foreground" title="Parsed by the fast model; no Claude call">
            <ZapIcon className="size-3" /> fast path · no Claude
          </span>
        )}
        {meta.fast_path === false && meta.fallback_reason && (
          <span className="text-[11px] text-muted-foreground">Sent to the orchestrator: {meta.fallback_reason}</span>
        )}
      </div>
    )
  }
  if (meta.kind === "plan" && meta.plan_id) {
    const plan: PlanRecord | undefined = chat.plans[String(meta.plan_id)]
    return plan ? <LivePlanCard plan={plan} /> : <p className="text-xs text-muted-foreground">{message.content}</p>
  }
  if (meta.kind === "result") return <ResultCard message={message} />
  if (message.role === "system") {
    const error = meta.kind === "error"
    return (
      <div
        className={cn(
          "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs",
          error ? "border-destructive/30 bg-destructive/5" : "bg-muted/40",
        )}
      >
        {error ? <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0 text-destructive" /> : <InfoIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />}
        <span className="text-foreground/80">{message.content}</span>
      </div>
    )
  }
  // assistant
  const streaming = Boolean(meta.streaming)
  const text = streaming ? (stream ?? "") : message.content
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-brand-muted">
        <BotIcon className="size-3.5 text-brand" />
      </div>
      <div className="min-w-0 flex-1 text-sm leading-6 [&_a]:text-brand [&_a]:underline [&_li]:ml-4 [&_ol]:list-decimal [&_p]:my-1.5 [&_strong]:font-semibold [&_ul]:list-disc">
        {text ? <ReactMarkdown>{text}</ReactMarkdown> : null}
        {streaming && (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2Icon className="size-3 animate-spin" /> {activity ?? (text ? "Writing…" : "Thinking…")}
          </p>
        )}
        {!streaming && meta.error && (
          <p className="mt-1 flex items-start gap-1.5 text-xs text-destructive">
            <AlertTriangleIcon className="mt-0.5 size-3 shrink-0" /> {meta.error}
          </p>
        )}
        {!streaming && (meta.tools?.length ?? 0) > 0 && (
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <WrenchIcon className="size-3" />
            {[...new Set(meta.tools)].map((t) => (
              <span key={t} className="font-mono">
                {t}
              </span>
            ))}
            {meta.duration_ms ? <span>· {(meta.duration_ms / 1000).toFixed(1)}s</span> : null}
          </p>
        )}
      </div>
    </div>
  )
}
