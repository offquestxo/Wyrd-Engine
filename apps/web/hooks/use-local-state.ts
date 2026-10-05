"use client"

import { useCallback, useMemo, useSyncExternalStore } from "react"

const EVENT = "wyrd:local-state"

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback)
  window.addEventListener(EVENT, callback)
  return () => {
    window.removeEventListener("storage", callback)
    window.removeEventListener(EVENT, callback)
  }
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/** useState persisted to localStorage (per-browser UI preferences only). */
export function useLocalState<T>(key: string, initial: T) {
  const raw = useSyncExternalStore(subscribe, () => read(key), () => null)
  const value = useMemo<T>(() => {
    if (raw === null) return initial
    try {
      return JSON.parse(raw) as T
    } catch {
      return initial
    }
  }, [raw, initial])

  const update = useCallback(
    (next: T) => {
      try {
        localStorage.setItem(key, JSON.stringify(next))
      } catch {
        // storage unavailable: preference just won't persist
      }
      window.dispatchEvent(new Event(EVENT))
    },
    [key],
  )
  return [value, update] as const
}

/** False during server render and hydration, true afterwards. */
export function useMounted(): boolean {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  )
}
