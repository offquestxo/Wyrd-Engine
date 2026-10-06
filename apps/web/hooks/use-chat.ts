"use client"

// Chat threads over the real API. Replies stream in over SSE:
//   chat.message → a message was created or updated
//   chat.delta   → streaming text for an assistant message (appended locally)
//   chat.status  → the orchestrator started/finished working on a chat
//   chat.tool    → the orchestrator called an engine tool (shown as activity)
//   chat.changed / plan.status → refetch (title, session, plan cards)
//
// Live updates live in a local overlay, stamped with the time they arrived, and are merged
// over the last fetch only if they're newer than it. SWR's cache is never mutated directly:
// a local mutate() while a fetch is in flight makes SWR discard that fetch.

import { useEffect, useMemo, useRef, useState } from "react"
import useSWR from "swr"

import { useEngineEvent } from "@/hooks/use-events"
import { fetcher } from "@/lib/api"
import type { ChatDetail, ChatMessageRecord, ChatSummary } from "@/lib/types"

export function useChats() {
  const swr = useSWR<ChatSummary[]>("/api/chats", fetcher)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  useEngineEvent(["chat.changed", "chat.status"], () => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => void swr.mutate(), 250)
  })
  return swr
}

interface Stamped<T> {
  value: T
  at: number
}

interface Fetched {
  chat: ChatDetail
  at: number // when the request started
}

async function fetchChat(path: string): Promise<Fetched> {
  const at = Date.now()
  return { chat: await fetcher<ChatDetail>(path), at }
}

export function useChat(id: number | null) {
  const swr = useSWR<Fetched>(id ? `/api/chats/${id}` : null, fetchChat)
  const [overlay, setOverlay] = useState<Record<number, Stamped<ChatMessageRecord>>>({})
  const [busy, setBusy] = useState<Stamped<boolean> | null>(null)
  // Streaming text per assistant message id, until its final chat.message arrives.
  const [streams, setStreams] = useState<Record<number, string>>({})
  const [activity, setActivity] = useState<string | null>(null)
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(refetchTimer.current), [])
  const refetch = () => {
    clearTimeout(refetchTimer.current)
    refetchTimer.current = setTimeout(() => void swr.mutate(), 150)
  }

  /** Show a message right away (e.g. the one just sent). */
  const addLocal = (message: ChatMessageRecord) =>
    setOverlay((o) => ({ ...o, [message.id]: { value: message, at: Date.now() } }))

  useEngineEvent(["chat.message", "chat.delta", "chat.status", "chat.tool", "chat.changed", "plan.status"], (event) => {
    const data = event.data
    if (event.type === "plan.status") {
      if (data.chat_id === id || String(data.plan_id) in (swr.data?.chat.plans ?? {})) refetch()
      return
    }
    if (data.chat_id !== id) return
    if (event.type === "chat.changed") {
      if (!data.deleted) refetch() // title or session changed
    } else if (event.type === "chat.delta") {
      const mid = Number(data.message_id)
      setStreams((s) => ({ ...s, [mid]: (s[mid] ?? "") + String(data.text ?? "") }))
      setActivity(null)
    } else if (event.type === "chat.tool") {
      setActivity(`Using ${String(data.tool).replaceAll("_", " ")}…`)
    } else if (event.type === "chat.status") {
      if (!data.busy) setActivity(null)
      setBusy({ value: Boolean(data.busy), at: Date.now() })
    } else if (event.type === "chat.message") {
      const message = data.message as ChatMessageRecord
      if (!message.metadata?.streaming) {
        setStreams((s) => {
          if (!(message.id in s)) return s
          const next = { ...s }
          delete next[message.id]
          return next
        })
      }
      addLocal(message)
      // Plan cards need the plan itself, which only the full fetch carries.
      if (message.metadata?.kind === "plan") refetch()
    }
  })

  const fetched = swr.data
  const chat = useMemo<ChatDetail | undefined>(() => {
    if (!fetched) return undefined
    const byId = new Map(fetched.chat.messages.map((m) => [m.id, m]))
    for (const entry of Object.values(overlay)) {
      if (entry.value.chat_id !== fetched.chat.id) continue
      if (!byId.has(entry.value.id) || entry.at > fetched.at) byId.set(entry.value.id, entry.value)
    }
    return {
      ...fetched.chat,
      busy: busy && busy.at > fetched.at ? busy.value : fetched.chat.busy,
      messages: [...byId.values()].sort((a, b) => a.id - b.id),
    }
  }, [fetched, overlay, busy])

  return {
    data: chat,
    error: swr.error as Error | undefined,
    isLoading: swr.isLoading,
    mutate: () => swr.mutate(),
    addLocal,
    streams,
    activity,
  }
}
