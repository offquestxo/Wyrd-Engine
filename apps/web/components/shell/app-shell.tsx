"use client"

import { PanelRightOpenIcon } from "lucide-react"
import { useRouter } from "next/navigation"
import { type ReactNode, useEffect, useRef, useState } from "react"

import { CommandPalette } from "@/components/shell/command-palette"
import { EngineBanner } from "@/components/shell/engine-banner"
import { RunPanel } from "@/components/shell/run-panel"
import { Sidebar } from "@/components/shell/sidebar"
import { Button } from "@/components/ui/button"
import { useLocalState } from "@/hooks/use-local-state"
import { NAV } from "@/lib/nav"

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))
}

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [panelOpen, setPanelOpen] = useLocalState("wyrd.panelOpen", true)
  const gPressedAt = useRef(0)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setPaletteOpen((open) => !open)
        return
      }
      if (mod && e.key === ".") {
        e.preventDefault()
        setPanelOpen(!panelOpen)
        return
      }
      if (mod || e.altKey || isTyping(e.target)) return
      if (e.key === "g") {
        gPressedAt.current = Date.now()
        return
      }
      if (Date.now() - gPressedAt.current < 1000) {
        const item = NAV.find((n) => n.key === e.key)
        if (item) {
          e.preventDefault()
          router.push(item.href)
        }
        gPressedAt.current = 0
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [router, panelOpen, setPanelOpen])

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar onOpenPalette={() => setPaletteOpen(true)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <EngineBanner />
        <main className="relative min-h-0 flex-1 overflow-y-auto">
          {!panelOpen && (
            <Button
              variant="ghost"
              size="icon-sm"
              className="absolute top-3 right-3 z-10"
              onClick={() => setPanelOpen(true)}
              aria-label="Open live panel (⌘.)"
            >
              <PanelRightOpenIcon />
            </Button>
          )}
          {children}
        </main>
      </div>
      {panelOpen && <RunPanel onClose={() => setPanelOpen(false)} />}
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onTogglePanel={() => setPanelOpen(!panelOpen)}
      />
    </div>
  )
}
