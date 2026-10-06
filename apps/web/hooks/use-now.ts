"use client"

import { useEffect, useState } from "react"

/** Current time, re-rendering every `intervalMs` (for elapsed timers). */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(t)
  }, [intervalMs])
  return now
}
