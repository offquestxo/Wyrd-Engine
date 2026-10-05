import type { Metadata } from "next"
import { Suspense } from "react"

import { LoadingState } from "@/components/common/states"
import { ChatView } from "./chat-view"

export const metadata: Metadata = { title: "Chat" }

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="p-8"><LoadingState /></div>}>
      <ChatView />
    </Suspense>
  )
}
