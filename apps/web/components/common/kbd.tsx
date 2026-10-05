import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "rounded border border-border bg-muted px-1 py-px font-mono text-[10px] text-muted-foreground",
        className,
      )}
    >
      {children}
    </kbd>
  )
}
