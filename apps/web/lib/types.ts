// Shared types. Field names mirror the backend (SPEC §7) so mocks swap for real data cleanly.

export const STORY_STATUSES = [
  "Inbox",
  "Shortlisted",
  "Researching",
  "Scripting",
  "Fact-check",
  "Recording",
  "Editing",
  "Published",
  "Archived",
] as const
export type StoryStatus = (typeof STORY_STATUSES)[number]

export const SERIES = [
  "Childhood Brands",
  "Tech Graveyard",
  "Fraud Files",
  "Everyday Genius",
  "Comebacks",
  "Recent Collapses",
] as const
export type Series = (typeof SERIES)[number]

export type StoryFormat = "Short" | "Long"

export interface StoryScores {
  drama: number
  twist: number
  relatability: number
  visual_potential: number
  hook_number: number
  freshness: number
}

export interface StorySource {
  id: number
  url: string
  title: string
  source_type: "primary" | "secondary"
  excerpt?: string
}

export interface Story {
  id: number
  slug: string
  title: string
  company: string
  status: StoryStatus
  series: Series
  format: StoryFormat
  hook: string
  scores: StoryScores
  gap_score: number | null
  from_outlier: boolean
  notes?: string
  sources: StorySource[]
  dossier_versions: number[]
  created_at: string
  updated_at: string
}

export type AgentName = "scout" | "outlier" | "researcher"
export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled"

export interface RunLog {
  ts: string
  level: "debug" | "info" | "warn" | "error"
  message: string
}

export interface AgentRun {
  id: number
  agent: AgentName
  params: Record<string, unknown>
  status: RunStatus
  started_at: string | null
  finished_at: string | null
  current_step?: string
  progress?: number
  summary?: string
  error?: string
  providers: string[]
  logs: RunLog[]
}

export interface PlanStep {
  order: number
  agent: AgentName
  params: Record<string, unknown>
  providers: string[]
  youtube_units?: number
  uses_claude: boolean
}

export interface Plan {
  id: number
  chat_id: number
  status: "pending" | "approved" | "cancelled" | "done" | "failed"
  summary: string
  steps: PlanStep[]
  created_at: string
}

export type MessageRole = "user" | "assistant" | "system" | "agent"

export interface ChatMessage {
  id: number
  role: MessageRole
  content: string
  created_at: string
  plan?: Plan
  result?: { agent: AgentName; run_id: number; headline: string; items: string[]; href: string }
}

export interface ChatThread {
  id: number
  title: string
  updated_at: string
  messages: ChatMessage[]
}

export interface Dossier {
  id: number
  story_id: number
  story_title: string
  slug: string
  version: number
  versions: number[]
  markdown: string
  sources: { n: number; url: string; title: string; primary: boolean }[]
  flags: number
  created_at: string
}

export interface OutlierVideo {
  id: number
  video_id: string
  channel: string
  title: string
  is_short: boolean
  views: number
  channel_median: number
  outlier_score: number
  published_at: string
  analysis: {
    topic: string
    company_type: string
    hook_pattern: string
    why_it_worked: string
    wyrd_angle: string
  }
}

export interface UsageMeter {
  provider: string
  label: string
  unit: string
  used: number
  limit: number | null
  calls: number
  errors: number
  fallbacks: number
  note?: string
}

// --- real backend responses -------------------------------------------------
export interface KeyStatus {
  env: string
  provider: string | null
  purpose: string
  status: "set" | "missing" | "failing"
  preview: string
  testable: boolean
  last_test: ConnectionTest | null
}

export interface ConnectionTest {
  provider: string
  ok: boolean
  detail: string
  latency_ms: number
  auth?: string | null
}

export interface ProviderSummary {
  provider: string
  key_env: string | null
  status: string
  models: Record<string, string>
  model_limits: Record<string, { rpm: number | null; rpd: number | null; tpm: number | null; tpd: number | null }>
  limits: Record<string, number | null>
}

export interface AgentSettings {
  name: string
  description: string
  uses_claude: boolean
  uses_youtube_quota: boolean
  available: boolean
  auto_approve: boolean
}

export interface ConfigFile {
  name: string
  path: string
  raw: string
  data: Record<string, unknown>
}

export interface ClaudeStatus {
  installed: boolean
  logged_in: boolean
  version: string | null
  auth_method: string | null
  detail: string
}

export interface EngineEvent {
  id: number
  type: string
  ts: string
  data: Record<string, unknown>
}
