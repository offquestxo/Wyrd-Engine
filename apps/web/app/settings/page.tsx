import type { Metadata } from "next"
import { Suspense } from "react"

import { LoadingState } from "@/components/common/states"
import { SettingsView } from "./settings-view"

export const metadata: Metadata = { title: "Settings" }

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className="p-8"><LoadingState /></div>}>
      <SettingsView />
    </Suspense>
  )
}
