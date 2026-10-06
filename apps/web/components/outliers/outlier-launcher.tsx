"use client"

import { FlameIcon, Loader2Icon } from "lucide-react"
import { useState } from "react"

import { useProposePlan } from "@/components/plans/propose-provider"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

/** Pick @outlier parameters, then propose a plan (the plan card shows the YouTube unit estimate). */
export function OutlierLauncher() {
  const propose = useProposePlan()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [channels, setChannels] = useState("")
  const [perChannel, setPerChannel] = useState(50)
  const [threshold, setThreshold] = useState(3)
  const [format, setFormat] = useState("both")

  const submit = async () => {
    setBusy(true)
    const list = channels.split(/[\s,]+/).map((c) => c.trim()).filter(Boolean)
    const params: Record<string, unknown> = { videos_per_channel: perChannel, threshold, format }
    if (list.length) params.channels = list.map((c) => (c.startsWith("@") ? c : `@${c}`))
    await propose(
      "outlier",
      params,
      `Scan ${list.length ? list.join(", ") : "all competitor channels"} for videos ≥ ${threshold}× their median`,
    )
    setBusy(false)
    setOpen(false)
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)} className="bg-brand text-brand-foreground hover:bg-brand/90">
        <FlameIcon /> Run @outlier
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Run @outlier</DialogTitle>
            <DialogDescription>Find competitor videos that beat their channel’s median. You’ll review the plan and its YouTube cost first.</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              void submit()
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="outlier-channels">Channels (optional)</Label>
              <Input
                id="outlier-channels"
                value={channels}
                onChange={(e) => setChannels(e.target.value)}
                placeholder="All channels in Settings → Channels"
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="outlier-per">Videos each</Label>
                <Input id="outlier-per" type="number" min={1} max={500} value={perChannel}
                  onChange={(e) => setPerChannel(Math.max(1, Math.min(500, Number(e.target.value) || 1)))} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="outlier-threshold">Threshold ×</Label>
                <Input id="outlier-threshold" type="number" min={1} step={0.5} value={threshold}
                  onChange={(e) => setThreshold(Math.max(1, Number(e.target.value) || 3))} />
              </div>
              <div className="space-y-1.5">
                <Label>Format</Label>
                <Select value={format} onValueChange={setFormat}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="both">Both</SelectItem>
                    <SelectItem value="shorts">Shorts</SelectItem>
                    <SelectItem value="long">Long</SelectItem>
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
