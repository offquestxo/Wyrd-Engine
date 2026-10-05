import { Suspense } from "react"

import { LoadingState } from "@/components/common/states"
import { RunView } from "./run-view"

export default async function RunPage({ params }: PageProps<"/runs/[id]">) {
  const { id } = await params
  return (
    <Suspense fallback={<div className="p-8"><LoadingState /></div>}>
      <RunView id={Number(id)} />
    </Suspense>
  )
}
