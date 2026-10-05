"use client"

// One shared EventSource to the backend SSE stream (/api/events), with reconnect.

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react"

import { API_BASE } from "@/lib/api"
import type { EngineEvent } from "@/lib/types"

type ConnectionState = "connecting" | "open" | "closed"

interface EventsValue {
  status: ConnectionState
  events: EngineEvent[]
  clear: () => void
}

const EventsContext = createContext<EventsValue>({ status: "connecting", events: [], clear: () => {} })

const EVENT_TYPES = ["system", "provider.tested", "config.saved", "settings.changed", "run.log", "run.status"]
const MAX_EVENTS = 200

export function EventsProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<ConnectionState>("connecting")
  const [events, setEvents] = useState<EngineEvent[]>([])
  const retryRef = useRef(0)

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
        try {
          const event = JSON.parse(e.data) as EngineEvent
          setEvents((prev) => (prev.some((p) => p.id === event.id) ? prev : [...prev, event].slice(-MAX_EVENTS)))
        } catch {
          // ignore malformed events
        }
      }
      for (const type of EVENT_TYPES) source.addEventListener(type, onEvent)
      source.onmessage = onEvent
      source.onerror = () => {
        source?.close()
        if (disposed) return
        setStatus("closed")
        // Back off 1s, 2s, 4s… up to 30s. The browser resends Last-Event-ID only on its own
        // retries, so we may see a few replayed events; duplicates are dropped by id above.
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

  return (
    <EventsContext.Provider value={{ status, events, clear: () => setEvents([]) }}>
      {children}
    </EventsContext.Provider>
  )
}

export const useEvents = () => useContext(EventsContext)
