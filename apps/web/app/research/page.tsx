import type { Metadata } from "next"
import { Suspense } from "react"

import { LoadingState } from "@/components/common/states"
import { ResearchView } from "./research-view"

export const metadata: Metadata = { title: "Research" }

export default function ResearchPage() {
  return (
    <Suspense fallback={<div className="p-8"><LoadingState /></div>}>
      <ResearchView />
    </Suspense>
  )
}
