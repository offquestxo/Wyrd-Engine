"use client"

import { Loader2Icon, RadarIcon } from "lucide-react"
import { useState } from "react"

import { useProposePlan } from "@/components/plans/propose-provider"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { SERIES } from "@/lib/types"

const ANY = "any"

/** Pick @scout parameters, then propose a plan (the owner approves it on the plan card). */
export function ScoutLauncher({ size = "sm" }: { size?: "sm" | "default" }) {
  const propose = useProposePlan()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState("both")
  const [topic, setTopic] = useState("")
  const [limit, setLimit] = useState(25)
  const [series, setSeries] = useState(ANY)

  const submit = async () => {
    setBusy(true)
    const params: Record<string, unknown> = { mode, limit }
    if (topic.trim()) params.topic = topic.trim()
    if (series !== ANY) params.series = series
    const what = [mode === "both" ? "news + evergreen" : mode, topic.trim() && `“${topic.trim()}”`]
      .filter(Boolean)
      .join(", ")
    await propose("scout", params, `Find up to ${limit} story leads (${what})`)
    setBusy(false)
    setOpen(false)
  }

  return (
    <>
      <Button size={size} onClick={() => setOpen(true)} className="bg-brand text-brand-foreground hover:bg-brand/90">
        <RadarIcon /> Run @scout
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Run @scout</DialogTitle>
            <DialogDescription>Find and score new story leads. You’ll review the plan before it runs.</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              void submit()
            }}
          >
            <div className="space-y-1.5">
              <Label>Mode</Label>
              <Select value={mode} onValueChange={setMode}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="both">News + evergreen gaps</SelectItem>
                  <SelectItem value="news">News (recent stories)</SelectItem>
                  <SelectItem value="evergreen">Evergreen (Wikipedia gaps, uses YouTube quota)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="scout-topic">Topic (optional)</Label>
              <Input id="scout-topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. fraud, restaurants" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="scout-limit">Limit</Label>
                <Input
                  id="scout-limit"
                  type="number"
                  min={1}
                  max={200}
                  value={limit}
                  onChange={(e) => setLimit(Math.max(1, Math.min(200, Number(e.target.value) || 1)))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Series</Label>
                <Select value={series} onValueChange={setSeries}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ANY}>Any series</SelectItem>
                    {SERIES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={busy} className="bg-brand text-brand-foreground hover:bg-brand/90">
                {busy && <Loader2Icon className="animate-spin" />} Propose plan
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
