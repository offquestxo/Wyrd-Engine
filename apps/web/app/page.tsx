import { Suspense } from "react"

import { LoadingState } from "@/components/common/states"
import { HomeView } from "./home-view"

export default function HomePage() {
  return (
    <Suspense fallback={<div className="p-8"><LoadingState /></div>}>
      <HomeView />
    </Suspense>
  )
}
