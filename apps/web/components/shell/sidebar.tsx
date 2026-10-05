"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

import { Kbd } from "@/components/common/kbd"
import { useEvents } from "@/hooks/use-events"
import { NAV } from "@/lib/nav"
import { cn } from "@/lib/utils"

export function Sidebar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const pathname = usePathname()
  const { status } = useEvents()

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="flex h-14 items-center px-4">
        <Link href="/" className="font-mono text-sm font-semibold tracking-tight text-foreground">
          wyrd<span className="text-brand">.exe</span>
        </Link>
      </div>

      <button
        onClick={onOpenPalette}
        className="mx-3 mb-3 flex items-center justify-between rounded-md border border-sidebar-border px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
      >
        Search or run…
        <Kbd>⌘K</Kbd>
      </button>

      <nav className="flex flex-1 flex-col gap-0.5 px-2" aria-label="Main">
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-foreground",
                active && "bg-sidebar-accent text-foreground",
              )}
            >
              <item.icon className={cn("size-4", active ? "text-brand" : "text-muted-foreground")} />
              <span className="flex-1">{item.label}</span>
              <span className="hidden font-mono text-[10px] text-muted-foreground/60 group-hover:inline">
                g {item.key}
              </span>
            </Link>
          )
        })}
      </nav>

      <div className="flex items-center gap-2 border-t border-sidebar-border px-4 py-3 text-xs text-muted-foreground">
        <span
          className={cn(
            "size-1.5 rounded-full",
            status === "open" ? "bg-success" : status === "connecting" ? "bg-warning" : "bg-destructive",
          )}
        />
        {status === "open" ? "Engine connected" : status === "connecting" ? "Connecting…" : "Engine offline"}
      </div>
    </aside>
  )
}
