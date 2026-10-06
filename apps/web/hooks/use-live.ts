"use client"

// SWR data that refreshes when the engine reports a relevant change over SSE.

import { useEffect, useRef } from "react"
import useSWR from "swr"

import { useEngineEvent } from "@/hooks/use-events"
import { fetcher } from "@/lib/api"
import type { ChannelRecord, OutlierVideo, PlanRecord, RunRecord, Story, UsageReport } from "@/lib/types"

/** Returns a function that runs `fn` at most once per `ms` (trailing call kept). */
function useThrottle(fn: () => void, ms: number) {
  const last = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const fnRef = useRef(fn)
  useEffect(() => {
    fnRef.current = fn
  })
  useEffect(() => () => clearTimeout(timer.current), [])
  return () => {
    const wait = last.current + ms - Date.now()
    if (wait <= 0) {
      last.current = Date.now()
      fnRef.current()
    } else if (!timer.current) {
      timer.current = setTimeout(() => {
        timer.current = undefined
        last.current = Date.now()
        fnRef.current()
      }, wait)
    }
  }
}

export function useRuns(query = "limit=20") {
  const swr = useSWR<RunRecord[]>(`/api/runs?${query}`, fetcher)
  const refresh = useThrottle(() => void swr.mutate(), 400)
  useEngineEvent(["run.status", "run.log"], refresh)
  return swr
}

export function usePlans(status?: string) {
  const swr = useSWR<PlanRecord[]>(`/api/plans${status ? `?status=${status}` : ""}`, fetcher)
  const refresh = useThrottle(() => void swr.mutate(), 300)
  useEngineEvent(["plan.status", "run.status"], refresh)
  return swr
}

export function useUsage() {
  const swr = useSWR<UsageReport>("/api/usage", fetcher, { refreshInterval: 15_000 })
  const refresh = useThrottle(() => void swr.mutate(), 2000)
  useEngineEvent(["run.status", "provider.tested"], refresh)
  return swr
}

/** One run with its full log; new log lines are appended live without refetching. */
export function useRun(id: number) {
  const swr = useSWR<RunRecord>(`/api/runs/${id}`, fetcher)
  const refresh = useThrottle(() => void swr.mutate(), 300)
  useEngineEvent(["run.log", "run.status"], (event) => {
    if (event.data.run_id !== id) return
    if (event.type === "run.status") return refresh()
    void swr.mutate(
      (run) =>
        run && {
          ...run,
          logs: [
            ...(run.logs ?? []),
            {
              id: Number(event.data.id),
              run_id: id,
              ts: String(event.data.ts),
              level: event.data.level as "info",
              message: String(event.data.message),
              data: null,
            },
          ].filter((entry, i, all) => all.findIndex((e) => e.id === entry.id) === i),
        },
      { revalidate: false },
    )
  })
  return swr
}

export function useStories() {
  const swr = useSWR<Story[]>("/api/stories", fetcher)
  const refresh = useThrottle(() => void swr.mutate(), 800)
  useEngineEvent(["story.changed", "run.status"], (event) => {
    if (event.type === "story.changed" || event.data.status === "succeeded") refresh()
  })
  return swr
}

export function useStory(id: number | null) {
  const swr = useSWR<Story>(id ? `/api/stories/${id}` : null, fetcher)
  useEngineEvent(["story.changed"], (event) => {
    if (event.data.story_id === id) void swr.mutate()
  })
  return swr
}

export function useOutliers() {
  const swr = useSWR<OutlierVideo[]>("/api/outliers", fetcher)
  const refresh = useThrottle(() => void swr.mutate(), 800)
  useEngineEvent(["run.status", "story.changed"], (event) => {
    if (event.type === "story.changed" || (event.data.agent === "outlier" && event.data.status === "succeeded"))
      refresh()
  })
  return swr
}

export function useChannels() {
  return useSWR<ChannelRecord[]>("/api/channels", fetcher)
}
