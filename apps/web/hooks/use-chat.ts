"use client"

// Chat threads over the real API. Replies stream in over SSE:
//   chat.message → a message was created or updated (upserted into the thread)
//   chat.delta   → streaming text for an assistant message (appended locally)
//   chat.status  → the orchestrator started/finished working on a chat
//   chat.tool    → the orchestrator called an engine tool (shown as activity)
//   plan.status  → a plan card in this thread changed (refetch)

import { useEffect, useRef, useState } from "react"
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

function upsert(messages: ChatMessageRecord[], message: ChatMessageRecord) {
  const i = messages.findIndex((m) => m.id === message.id)
  if (i === -1) return [...messages, message].sort((a, b) => a.id - b.id)
  const next = messages.slice()
  next[i] = message
  return next
}

export function useChat(id: number | null) {
  const swr = useSWR<ChatDetail>(id ? `/api/chats/${id}` : null, fetcher)
  // Streaming text per assistant message id, until its final chat.message arrives.
  const [streams, setStreams] = useState<Record<number, string>>({})
  const [activity, setActivity] = useState<string | null>(null)

  // Apply a local change only once the thread has loaded. A mutate() during the first fetch
  // makes SWR drop that fetch's result (SSE replays recent events right after connecting).
  const update = (fn: (chat: ChatDetail) => ChatDetail) => {
    if (!swr.data) return void swr.mutate()
    void swr.mutate((chat) => chat && fn(chat), { revalidate: false })
  }

  useEngineEvent(["chat.message", "chat.delta", "chat.status", "chat.tool", "chat.changed", "plan.status"], (event) => {
    const data = event.data
    if (event.type === "chat.changed") {
      if (data.chat_id === id && !data.deleted) void swr.mutate() // title or session changed
      return
    }
    if (event.type === "plan.status") {
      const plans = swr.data?.plans ?? {}
      if (String(data.plan_id) in plans || data.chat_id === id) void swr.mutate()
      return
    }
    if (data.chat_id !== id) return
    if (event.type === "chat.delta") {
      const mid = Number(data.message_id)
      setStreams((s) => ({ ...s, [mid]: (s[mid] ?? "") + String(data.text ?? "") }))
      setActivity(null)
    } else if (event.type === "chat.tool") {
      setActivity(`Using ${String(data.tool).replaceAll("_", " ")}…`)
    } else if (event.type === "chat.status") {
      if (!data.busy) setActivity(null)
      update((chat) => ({ ...chat, busy: Boolean(data.busy) }))
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
      const needsPlan = message.metadata?.kind === "plan" && !swr.data?.plans?.[String(message.metadata.plan_id)]
      if (needsPlan) void swr.mutate()
      else update((chat) => ({ ...chat, messages: upsert(chat.messages, message) }))
    }
  })

  return { ...swr, streams, activity }
}
