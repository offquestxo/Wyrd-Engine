"use client"

import { useRouter } from "next/navigation"
import { useCallback } from "react"

import { useProposePlan } from "@/components/plans/propose-provider"

/**
 * Start an agent the same way everywhere (sidebar Agents, ⌘K, Home "New run"): propose a plan
 * with sensible defaults, then the owner reviews and edits it on the plan card before it runs.
 * Agents that need a subject (researcher) open the chat composer with the @mention ready.
 */
export function useStartAgent() {
  const propose = useProposePlan()
  const router = useRouter()
  return useCallback(
    (agent: string) => {
      if (agent === "scout") return void propose("scout", { mode: "both", limit: 25 }, "Find up to 25 story leads (news + evergreen)")
      if (agent === "outlier") return void propose("outlier", {}, "Scan all competitor channels for outliers")
      router.push(`/chat?compose=${encodeURIComponent(`@${agent} `)}`)
    },
    [propose, router],
  )
}
