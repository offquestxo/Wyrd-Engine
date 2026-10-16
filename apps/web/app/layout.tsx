import type { Metadata, Viewport } from "next"
import { Bricolage_Grotesque, Geist, Geist_Mono } from "next/font/google"

import { ProposeProvider } from "@/components/plans/propose-provider"
import { AppShell } from "@/components/shell/app-shell"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { EventsProvider } from "@/hooks/use-events"

import "./globals.css"

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] })
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] })
// Creative pages only: headings on Chat/Stories and the figures inside thumbnail blocks.
const bricolage = Bricolage_Grotesque({ variable: "--font-bricolage", subsets: ["latin"], weight: ["500", "700", "800"] })

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
  themeColor: "#07080c",
  colorScheme: "dark",
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`dark ${geistSans.variable} ${geistMono.variable} ${bricolage.variable}`}>
      <body className="antialiased">
        <TooltipProvider delayDuration={300}>
          <EventsProvider>
            <ProposeProvider>
              <AppShell>{children}</AppShell>
            </ProposeProvider>
          </EventsProvider>
          <Toaster theme="dark" position="bottom-center" />
        </TooltipProvider>
      </body>
    </html>
  )
}
