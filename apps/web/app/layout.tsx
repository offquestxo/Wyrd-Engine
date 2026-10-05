import type { Metadata, Viewport } from "next"
import { Geist, Geist_Mono } from "next/font/google"

import { AppShell } from "@/components/shell/app-shell"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { EventsProvider } from "@/hooks/use-events"

import "./globals.css"

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] })
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] })

export const metadata: Metadata = {
  title: { default: "wyrd.exe", template: "%s · wyrd.exe" },
  description: "Story engine for wyrd.exe: find, score, and research true business stories.",
  applicationName: "wyrd.exe",
  appleWebApp: { capable: true, title: "wyrd.exe", statusBarStyle: "black-translucent" },
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }, { url: "/icon-192.png", sizes: "192x192" }],
    apple: "/apple-touch-icon.png",
  },
}

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  colorScheme: "dark",
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`dark ${geistSans.variable} ${geistMono.variable}`}>
      <body className="antialiased">
        <TooltipProvider delayDuration={300}>
          <EventsProvider>
            <AppShell>{children}</AppShell>
          </EventsProvider>
          <Toaster theme="dark" position="bottom-center" />
        </TooltipProvider>
      </body>
    </html>
  )
}
