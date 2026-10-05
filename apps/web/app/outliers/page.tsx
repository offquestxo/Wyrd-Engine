import type { Metadata } from "next"
import { Suspense } from "react"

import { LoadingState } from "@/components/common/states"
import { OutliersView } from "./outliers-view"

export const metadata: Metadata = { title: "Outliers" }

export default function OutliersPage() {
  return (
    <Suspense fallback={<div className="p-8"><LoadingState /></div>}>
      <OutliersView />
    </Suspense>
  )
}
