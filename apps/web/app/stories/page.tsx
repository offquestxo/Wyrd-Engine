import type { Metadata } from "next"
import { Suspense } from "react"

import { LoadingState } from "@/components/common/states"
import { StoriesView } from "./stories-view"

export const metadata: Metadata = { title: "Stories" }

export default function StoriesPage() {
  return (
    <Suspense fallback={<div className="p-8"><LoadingState /></div>}>
      <StoriesView />
    </Suspense>
  )
}
