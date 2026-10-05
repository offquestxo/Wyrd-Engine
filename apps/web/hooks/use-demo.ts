"use client"

// Loads sample data like a real request would, so every page exercises its loading,
// empty, and error states. Append ?state=loading|empty|error to any page to preview them.

import { useSearchParams } from "next/navigation"
import { useCallback, useEffect, useState } from "react"

export type DemoState = "loading" | "empty" | "error" | null

export function useDemo<T>(data: T, empty: T, delayMs = 350) {
  const forced = useSearchParams().get("state") as DemoState
  const [attempt, setAttempt] = useState(0)
  const key = `${forced}:${attempt}`
  const [loadedKey, setLoadedKey] = useState<string | null>(null)

  useEffect(() => {
    if (forced === "loading") return
    const timer = setTimeout(() => setLoadedKey(key), delayMs)
    return () => clearTimeout(timer)
  }, [forced, key, delayMs])

  const retry = useCallback(() => setAttempt((a) => a + 1), [])
  const loaded = loadedKey === key
  const error = loaded && forced === "error" ? new Error("Sample error: the engine API returned 500.") : null
  return {
    data: !loaded || error ? undefined : forced === "empty" ? empty : data,
    isLoading: !loaded,
    error,
    retry,
  }
}
