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
  story_id: number
  url: string
  title: string | null
  source_type: "primary" | "secondary"
  excerpt: string | null
  added_by: string | null
}

/** A story as returned by /api/stories (sources/dossier_versions only on the detail call). */
export interface Story {
  id: number
  slug: string
  title: string
  company: string | null
  status: StoryStatus
  series: Series | null
  format: StoryFormat | null
  hook: string | null
  scores: (Partial<StoryScores> & { total?: number | null }) | null
  gap_score: number | null
  outlier_ref: number | null
  notes: string | null
  created_at: string
  updated_at: string
  total_score: number | null
  source_count: number
  sources?: StorySource[]
  dossier_versions?: number[]
}

export type AgentName = "scout" | "outlier" | "researcher"
export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled"

export interface OutlierAnalysisRecord {
  topic: string
  company_type: string
  hook_pattern: string
  why_it_worked: string
  wyrd_angle: string
}

/** A scanned competitor video from /api/outliers. */
export interface OutlierVideo {
  id: number
  video_id: string
  channel_id: number
  channel_name: string | null
  channel_handle: string | null
  title: string
  url: string
  thumbnail_url: string | null
  is_short: boolean
  duration_s: number | null
  views: number | null
  channel_median: number | null
  outlier_score: number | null
  published_at: string | null
  analysis: OutlierAnalysisRecord | null
  story_id: number | null
}

export interface ChannelRecord {
  id: number
  handle: string
  channel_id: string | null
  name: string | null
  last_scanned_at: string | null
  videos: number
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
  note?: string | null
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
  hidden?: boolean
  implemented?: boolean
  arrives_in?: string | null
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

// --- Phase 2: real runs, plans, usage ----------------------------------------
export interface RunLogEntry {
  id: number
  run_id: number
  ts: string
  level: "debug" | "info" | "warn" | "error"
  message: string
  data: Record<string, unknown> | null
}

export interface RunRecord {
  id: number
  agent: string
  params: Record<string, unknown> | null
  status: RunStatus
  started_at: string | null
  finished_at: string | null
  created_at: string | null
  current_step: string | null
  progress: number | null
  result: Record<string, unknown> | null
  error: string | null
  plan_id: number | null
  log_tail?: RunLogEntry[]
  logs?: RunLogEntry[]
}

export interface PlanStepRecord {
  id: number
  order: number
  agent: string
  params: Record<string, unknown> | null
  status: string
  run_id: number | null
  uses_claude: boolean
  uses_youtube_quota: boolean
  estimate?: {
    youtube_search_calls?: number
    youtube_units?: number
    claude_turns?: number
    sources?: string[]
    note?: string
  } | null
  providers?: string[]
}

export interface PlanRecord {
  id: number
  chat_id: number | null
  status: "pending" | "approved" | "cancelled" | "done" | "failed"
  summary: string | null
  created_at: string
  decided_at: string | null
  steps: PlanStepRecord[]
}

export interface ModelUsage {
  alias: string
  id: string
  requests: number
  tokens: number
  errors: number
  fallbacks: number
  requests_last_min: number
  tokens_last_min: number
  limits: { rpm: number | null; rpd: number | null; tpm: number | null; tpd: number | null }
}

export interface ProviderMeter {
  provider: string
  label: string
  status: string
  used: number
  limit: number | null
  unit: string
  requests: number
  tokens: number
  errors: number
  fallbacks: number
  search_calls?: number
  search_limit?: number | null
  models: ModelUsage[]
  claude?: ClaudeUsage
}

export interface ClaudeUsage {
  chat_turns: number
  agent_runs: number
  duration_s: number
  turns: number
  soft_cap: number
  warn: boolean
  over: boolean
  rate_limit: { status?: string; resetsAt?: number; rateLimitType?: string } | null
}

export interface UsageReport {
  since: string
  timezone: string
  meters: ProviderMeter[]
}

// --- Phase 5: chat --------------------------------------------------------------
export type MessageRole = "user" | "assistant" | "system" | "agent"

export interface ResultItem {
  label: string
  detail?: string | null
  href: string
  id?: number | string | null
}

export interface ResultStep {
  order: number
  agent: string
  run_id: number | null
  status: string
  summary: string | null
  error: string | null
  youtube_units?: number | null
  items: ResultItem[]
}

export interface MessageMetadata {
  kind?: "plan" | "result" | "notice" | "error"
  plan_id?: number
  status?: string
  steps?: ResultStep[]
  streaming?: boolean
  engine_turn?: boolean
  tools?: string[]
  duration_ms?: number
  turns?: number
  model?: string | null
  error?: string | null
  fast_path?: boolean
  fallback_reason?: string
}

export interface ChatMessageRecord {
  id: number
  chat_id: number
  role: MessageRole
  content: string
  metadata: MessageMetadata
  created_at: string
}

export interface ChatSummary {
  id: number
  title: string
  has_session: boolean
  created_at: string
  updated_at: string
  busy: boolean
  message_count?: number
  preview?: string
}

export interface ChatDetail extends ChatSummary {
  messages: ChatMessageRecord[]
  plans: Record<string, PlanRecord>
}

// --- Phase 6: dossiers ----------------------------------------------------------
export interface DossierSource {
  n: number
  url: string
  title: string
  kind: string | null
  source_type: "primary" | "secondary"
  claims_checked: number
  claims_verified: number
}

export interface DossierSummary {
  id: number
  story_id: number
  story_title: string
  slug: string | null
  status: string | null
  version: number
  versions: number[]
  created_at: string
  run_id: number | null
  excerpt_check: { passed: number; failed: number }
  flags: number
  support_fallback: boolean
  support_checked_by: string[]
  source_count: number
  primary_count: number
}

export interface DossierDetail extends DossierSummary {
  markdown: string
  sources: DossierSource[]
  export_path: string | null
  second_opinion: {
    flags: { claim: string; issue: string; severity: "low" | "medium" | "high"; suggestion: string }[]
    overall: string | null
    resolutions: { claim: string; action: string; note: string }[]
  } | null
  checks: Record<string, unknown> | null
}

// --- Phase 7: Notion sync --------------------------------------------------------
export interface NotionSyncReport {
  ok: boolean
  mode: string
  started_at: string
  finished_at: string | null
  pulled: { story_id: number; title: string; from: Record<string, unknown>; to: Record<string, unknown> }[]
  created: number
  updated: number
  unchanged: number
  conflicts_local_won: number
  ignored_pages: number
  requests: number
  errors: string[]
}

export interface NotionStatus {
  configured: boolean
  token_set: boolean
  database_set: boolean
  auto_sync: boolean
  syncing: boolean
  stories: number
  linked: number
  pending: number
  last_sync: NotionSyncReport | null
  version: string
}
