import { CompassIcon } from "lucide-react"
import Link from "next/link"

import { EmptyState } from "@/components/common/states"
import { Button } from "@/components/ui/button"

export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl px-8 py-24">
      <EmptyState
        icon={CompassIcon}
        title="Page not found"
        description="That page doesn't exist. Press ⌘K to jump anywhere."
        action={<Button size="sm" asChild><Link href="/">Go home</Link></Button>}
      />
    </div>
  )
}
