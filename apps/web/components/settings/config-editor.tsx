"use client"

import { AlertTriangleIcon, Loader2Icon, RotateCcwIcon, SaveIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { Kbd } from "@/components/common/kbd"
import { ErrorState, LoadingState } from "@/components/common/states"
import { Button } from "@/components/ui/button"
import { api, fetcher } from "@/lib/api"
import type { ConfigFile } from "@/lib/types"

/** Edits a config/*.yaml file as text. The backend validates before saving and keeps comments. */
export function ConfigEditor({ name, hint }: { name: string; hint?: string }) {
  const { data, error, isLoading, mutate } = useSWR<ConfigFile>(`/api/config/${name}`, fetcher)
  const [draft, setText] = useState<string | null>(null) // null = no local edits
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const text = draft ?? data?.raw ?? ""
  const dirty = data !== undefined && draft !== null && draft !== data.raw

  const save = async () => {
    setSaving(true)
    setProblem(null)
    try {
      const saved = await api<ConfigFile>(`/api/config/${name}`, { method: "PUT", body: JSON.stringify({ raw: text }) })
      await mutate(saved, { revalidate: false })
      setText(null)
      toast.success(`Saved ${saved.path}`)
    } catch (e) {
      setProblem((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (isLoading) return <LoadingState rows={6} />
  if (error) return <ErrorState error={error as Error} onRetry={() => mutate()} />

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="font-mono text-xs text-muted-foreground">
          {data?.path} {dirty && <span className="text-warning">· unsaved</span>}
        </p>
        <div className="flex items-center gap-2">
          {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
          <Button size="sm" variant="ghost" disabled={!dirty || saving} onClick={() => { setText(null); setProblem(null) }}>
            <RotateCcwIcon /> Revert
          </Button>
          <Button size="sm" disabled={!dirty || saving} onClick={save} className="bg-brand text-brand-foreground hover:bg-brand/90">
            {saving ? <Loader2Icon className="animate-spin" /> : <SaveIcon />} Save <Kbd className="border-brand-foreground/20 bg-transparent text-brand-foreground/70">⌘S</Kbd>
          </Button>
        </div>
      </div>
      {problem && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
          <span className="font-mono">Not saved: {problem}</span>
        </div>
      )}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "s") {
            e.preventDefault()
            if (dirty && !saving) void save()
          }
          if (e.key === "Tab") {
            e.preventDefault()
            const el = e.currentTarget
            const { selectionStart: s, selectionEnd: end } = el
            setText(text.slice(0, s) + "  " + text.slice(end))
            requestAnimationFrame(() => el.setSelectionRange(s + 2, s + 2))
          }
        }}
        spellCheck={false}
        aria-label={`${name}.yaml`}
        className="h-[28rem] w-full resize-y rounded-lg border bg-card p-4 font-mono text-xs leading-5 outline-none focus:border-brand/50"
      />
    </div>
  )
}
