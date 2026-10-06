"use client"

// One shared EventSource to the backend SSE stream (/api/events), with reconnect.
// Components read recent events (useEvents) or react to new ones (useEngineEvent).

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react"

import { API_BASE } from "@/lib/api"
import type { EngineEvent } from "@/lib/types"

type ConnectionState = "connecting" | "open" | "closed"
type Listener = (event: EngineEvent) => void

interface EventsValue {
  status: ConnectionState
  events: EngineEvent[]
  clear: () => void
  subscribe: (listener: Listener) => () => void
}

const EventsContext = createContext<EventsValue>({
  status: "connecting",
  events: [],
  clear: () => {},
  subscribe: () => () => {},
})

const EVENT_TYPES = [
  "system",
  "provider.tested",
  "config.saved",
  "settings.changed",
  "run.log",
  "run.status",
  "plan.status",
  "story.changed",
  "chat.changed",
  "chat.message",
  "chat.delta",
  "chat.status",
  "chat.tool",
]
const MAX_EVENTS = 300
// Streaming text deltas are delivered to listeners but not kept in the shared history.
const TRANSIENT = new Set(["chat.delta"])

export function EventsProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<ConnectionState>("connecting")
  const [events, setEvents] = useState<EngineEvent[]>([])
  const retryRef = useRef(0)
  const listeners = useRef(new Set<Listener>())
  const seen = useRef(new Set<number>())

  useEffect(() => {
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let disposed = false

    const connect = () => {
      setStatus("connecting")
      source = new EventSource(`${API_BASE}/api/events`)
      source.onopen = () => {
        retryRef.current = 0
        setStatus("open")
      }
      const onEvent = (e: MessageEvent<string>) => {
        let event: EngineEvent
        try {
          event = JSON.parse(e.data) as EngineEvent
        } catch {
          return // ignore malformed events
        }
        // The server replays recent history on reconnect; drop anything already seen.
        if (seen.current.has(event.id)) return
        seen.current.add(event.id)
        if (!TRANSIENT.has(event.type)) setEvents((prev) => [...prev, event].slice(-MAX_EVENTS))
        for (const listener of listeners.current) listener(event)
      }
      for (const type of EVENT_TYPES) source.addEventListener(type, onEvent)
      source.onmessage = onEvent
      source.onerror = () => {
        source?.close()
        if (disposed) return
        setStatus("closed")
        // Back off 1s, 2s, 4s… up to 30s.
        const delay = Math.min(30_000, 1000 * 2 ** retryRef.current++)
        timer = setTimeout(connect, delay)
      }
    }
    connect()
    return () => {
      disposed = true
      clearTimeout(timer)
      source?.close()
    }
  }, [])

  const subscribe = (listener: Listener) => {
    listeners.current.add(listener)
    return () => {
      listeners.current.delete(listener)
    }
  }

  return (
    <EventsContext.Provider value={{ status, events, clear: () => setEvents([]), subscribe }}>
      {children}
    </EventsContext.Provider>
  )
}

export const useEvents = () => useContext(EventsContext)

/** Calls `handler` for each new event whose type is in `types` (latest handler is used). */
export function useEngineEvent(types: string[], handler: (event: EngineEvent) => void) {
  const { subscribe } = useEvents()
  const handlerRef = useRef(handler)
  useEffect(() => {
    handlerRef.current = handler
  })
  const key = types.join(",")
  useEffect(() => {
    const wanted = new Set(key.split(","))
    return subscribe((event) => {
      if (wanted.has(event.type)) handlerRef.current(event)
    })
  }, [subscribe, key])
}
