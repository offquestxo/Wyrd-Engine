"use client"

import { MenuIcon, PanelRightOpenIcon } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { type ReactNode, useEffect, useRef, useState, useSyncExternalStore } from "react"

import { CommandPalette } from "@/components/shell/command-palette"
import { EngineBanner } from "@/components/shell/engine-banner"
import { RunPanel } from "@/components/shell/run-panel"
import { Sidebar } from "@/components/shell/sidebar"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { useLocalState } from "@/hooks/use-local-state"
import { NAV } from "@/lib/nav"

const WIDE = "(min-width: 1280px)"

function subscribeWide(callback: () => void) {
  const mq = window.matchMedia(WIDE)
  mq.addEventListener("change", callback)
  return () => mq.removeEventListener("change", callback)
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))
}

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [navOpen, setNavOpen] = useState(false)
  // null = never toggled: open on wide screens, closed on phones/tablets (it overlays there).
  const [panelPref, setPanelOpen] = useLocalState<boolean | null>("wyrd.panelOpen", null)
  const wide = useSyncExternalStore(subscribeWide, () => window.matchMedia(WIDE).matches, () => true)
  const panelOpen = panelPref ?? wide
  const [collapsed, setCollapsed] = useLocalState("wyrd.sidebarCollapsed", false)
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
      if (mod && e.key === "\\") {
        e.preventDefault()
        setCollapsed(!collapsed)
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
    const openPalette = () => setPaletteOpen(true)
    window.addEventListener("keydown", onKey)
    window.addEventListener("wyrd:open-palette", openPalette)
    return () => {
      window.removeEventListener("keydown", onKey)
      window.removeEventListener("wyrd:open-palette", openPalette)
    }
  }, [router, panelOpen, setPanelOpen, collapsed, setCollapsed])

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar
        className="hidden md:flex"
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed(!collapsed)}
        onOpenPalette={() => setPaletteOpen(true)}
      />
      {/* Phone/tablet: the sidebar slides in from a top bar. */}
      <Sheet open={navOpen} onOpenChange={setNavOpen}>
        <SheetContent side="left" className="w-[232px] border-none p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Sidebar
            className="w-full"
            onNavigate={() => setNavOpen(false)}
            onOpenPalette={() => {
              setNavOpen(false)
              setPaletteOpen(true)
            }}
          />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b px-2 md:hidden">
          <Button variant="ghost" size="icon-sm" onClick={() => setNavOpen(true)} aria-label="Open navigation">
            <MenuIcon />
          </Button>
          <Link href="/" className="font-mono text-sm font-semibold tracking-tight">
            wyrd<span className="text-brand-soft">.exe</span>
          </Link>
          <Button
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            onClick={() => setPanelOpen(!panelOpen)}
            aria-label="Toggle live panel"
          >
            <PanelRightOpenIcon />
          </Button>
        </div>
        <EngineBanner />
        <main className="relative min-h-0 flex-1 overflow-y-auto">
          {!panelOpen && (
            <Button
              variant="ghost"
              size="icon-sm"
              className="absolute top-3 right-3 z-10 hidden md:inline-flex"
              onClick={() => setPanelOpen(true)}
              aria-label="Open live panel (⌘.)"
            >
              <PanelRightOpenIcon />
            </Button>
          )}
          {children}
        </main>
      </div>
      {panelOpen && (
        // Inline on wide screens; an overlay on narrow ones so pages keep their width.
        <div className="fixed inset-y-0 right-0 z-40 flex max-w-[85vw] shadow-2xl lg:static lg:z-auto lg:max-w-none lg:shadow-none">
          <RunPanel onClose={() => setPanelOpen(false)} />
        </div>
      )}
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onTogglePanel={() => setPanelOpen(!panelOpen)}
      />
    </div>
  )
}
