"use client"

import { ErrorState } from "@/components/common/states"

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-xl px-8 py-24">
      <ErrorState error={error} onRetry={reset} />
    </div>
  )
}
