import { LoadingState } from "@/components/common/states"

export default function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <LoadingState rows={6} />
    </div>
  )
}
