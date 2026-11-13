// Mirrors the JSON the FastAPI backend returns (backend/app/domain/models.py, pipeline/run.py).

export type Seniority = 'ic' | 'manager' | 'director' | 'vp' | 'c_level'
export type HookPreference = 'company' | 'individual'
export type Priority = 'high' | 'medium' | 'low'
export type Tier = 'quick' | 'standard' | 'deep'

export const SIGNAL_CATEGORIES = [
  'role_change',
  'own_content',
  'press_quote',
  'award_or_speaking',
  'funding_mna',
  'leadership_hire',
  'hiring_pattern',
  'product_launch',
  'expansion',
  'partnership',
  'tech_stack_change',
  'strategy_earnings',
  'regulatory',
] as const
export type SignalCategory =
  | (typeof SIGNAL_CATEGORIES)[number]
  | 'layoffs'
  | 'litigation'
  | 'breach'
  | 'death_or_tragedy'
  | 'scandal'

export interface Persona {
  id: string
  title_patterns: string[]
  seniority: Seniority
  pains: string[]
  hook_preference: HookPreference
}

export interface ApprovedClaim {
  id: string
  text: string
  proof_url?: string | null
}

export interface SellerProfile {
  company: { name: string; domain: string; one_liner: string }
  offer: { product: string; problem_solved: string; how_it_works: string }
  icp: {
    industries: string[]
    employee_min: number | null
    employee_max: number | null
    regions: string[]
    exclusions: string[]
  }
  personas: Persona[]
  signal_to_pain: Partial<Record<SignalCategory, string[]>>
  approved_claims: ApprovedClaim[]
  never_claims: string[]
  tone: { voice: string; max_words: number; cta_style: string; banned_phrases: string[] }
  recency_windows_days: Partial<Record<SignalCategory, number>>
  hook_weights: Record<string, number>
  footer: string
}

export interface Campaign {
  id: string
  name: string
  objective: string
  persona_id: string
  segment: { industries: string[]; regions: string[]; stages: string[] }
  angle: string
  cta: string
  signal_priorities: Partial<Record<SignalCategory, Priority>>
  claims_to_emphasise: string[]
  extra_never_claims: string[]
  tone_adjustment: string
  hook_weight_overrides: Record<string, number>
}

export interface BriefIssue {
  code: string
  severity: 'error' | 'warning'
  message: string
  fix: string
}

export interface CampaignCheck {
  ok: boolean
  issues: BriefIssue[]
  provenance: Record<string, string>
}

export interface ProspectInput {
  company_name: string
  person_name?: string | null
  company_domain?: string | null
  title?: string | null
  linkedin_url?: string | null
  rep_notes?: string | null
  email?: string | null
}

/** The contact's address and where it came from. */
export interface FoundEmail {
  address: string
  source: 'rep' | 'page' | 'finder' // typed in, published on a page read, or Hunter
  url: string | null
  confidence: number | null
  status: string
}

export type RunState =
  | 'RUNNING'
  | 'DRAFT_READY'
  | 'DRAFT_HELD'
  | 'CONTACT_MOVED'
  | 'NEEDS_CLARIFICATION'
  | 'LOW_SIGNAL'
  | 'NOT_A_FIT'
  | 'NEEDS_REVIEW_SENSITIVE'
  | 'BLOCKED_SUPPRESSED'
  | 'DUPLICATE'
  | 'RECENTLY_CONTACTED'
  | 'INVALID_INPUT'
  | 'FAILED'

export type ReviewState = 'APPROVED' | 'APPROVED_WITH_EDITS' | 'REJECTED'

export interface RunSummary {
  id: string
  state: RunState
  review_state: ReviewState | null
  tier: Tier
  started_at?: string
  created_at: string
  finished_at: string | null
}

export interface Prospect extends ProspectInput {
  id: number
  last_run: RunSummary | null
}

export interface CsvPreview {
  rows: ProspectInput[]
  errors: { row: number; reason: string }[]
  unmapped_columns: string[]
  saved: number
}

export interface Evidence {
  id: string
  category: SignalCategory
  about: 'person' | 'company' | 'market'
  claim: string
  verbatim_quote: string
  url: string
  publisher: string
  source_type: string
  published_at: string | null
  event_date: string | null
  retrieved_at: string
  entity_match: string
  quote_verified: boolean
  entailment: 'supported' | 'partial' | 'unsupported' | null
  sensitivity: string
  round_found: number
}

export interface RankedHook {
  evidence: Evidence
  total: number
  dimension_scores: Record<string, number>
  reasons: Record<string, string>
}

export interface Contact {
  company_name: string
  company_domain: string | null
  person_name: string | null
  title: string | null
  evidence_url: string | null
  evidence_quote: string | null
}

export interface Draft {
  subject: string
  body: string
  citations: string[]
  /** The model that wrote it, e.g. "groq:openai/gpt-oss-120b" or "yours:anthropic:claude-opus-5-5". */
  written_by?: string | null
}

export interface ClaimVerdict {
  claim: string
  verdict: 'supported' | 'partial' | 'unsupported'
  evidence_id: string | null
  reason: string
}

export interface RunOutcome {
  state: RunState
  identity: {
    status: 'confirmed' | 'ambiguous' | 'suggested' | 'moved' | 'not_found'
    contact: Contact | null
    candidates: Contact[]
  } | null
  research: {
    ledger: Evidence[]
    rejected: { url: string; claim: string; reason: string }[]
    failures: { url: string; reason: string }[]
    rounds: number
    stop_reason: string
    searches_used: number
    pages_used: number
  } | null
  ranking: {
    ranked: RankedHook[]
    vetoed: { evidence: Evidence; reason: string }[]
    outcome: string
  } | null
  draft: Draft | null
  claims: ClaimVerdict[]
  problems: string[]
  notes: string[]
  email?: FoundEmail | null
}

export interface StageEvent {
  stage: string
  status: 'started' | 'progress' | 'done' | 'failed' | 'finished'
  summary: string
  items?: string[] // e.g. the facts a research round just verified
}

export interface Review {
  state: ReviewState
  draft: Draft
  reason: string | null
  at: string
}

export interface RunDetail extends RunSummary {
  campaign_id: string
  prospect_id: number
  prospect: ProspectInput
  brief: { objective: string; persona: Persona | null; pains: string[] }
  pinned_identity: Contact | null
  outcome: RunOutcome | null
  events: StageEvent[]
  review: Review | null
}

export interface Dashboard {
  runs_total: number
  by_state: Partial<Record<RunState, number>>
  by_review: Partial<Record<ReviewState, number>>
  approval_rate: number | null
  median_run_seconds?: number | null
  quota?: QuotaLine[]
}

export interface QuotaLine {
  name: string
  used: number
  limit: number
  unit: string
}

// ── model settings ──────────────────────────────────────────────────────────

export type ModelRole = 'reader' | 'judge' | 'writer' | 'checker'
export type ProviderId =
  'anthropic' | 'openai' | 'gemini' | 'groq' | 'openrouter' | 'custom' | 'claude_code'

export interface ModelChoice {
  provider: ProviderId
  model: string
}

export interface ModelProvider {
  id: ProviderId
  label: string
  suggested_models: string[]
  needs_base_url: boolean
  key_optional: boolean
  /** Uses this computer's own login (Claude Code); no key, local demos only. */
  local: boolean
  has_key: boolean
  key_hint: string | null
  base_url: string | null
}

export interface ModelSettings {
  can_save_keys: boolean
  providers: ModelProvider[]
  roles: Record<ModelRole, ModelChoice | null>
  free: Record<ModelRole, string[]>
}

export interface ModelTest {
  ok: boolean
  latency_ms: number
  error: string | null
}
