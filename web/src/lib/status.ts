// One vocabulary for run outcomes, used by every badge, chart and table in the app.

import type { ReviewState, RunState } from '@/api/types'

export type Tone = 'ready' | 'held' | 'sensitive' | 'clarify' | 'quiet' | 'running'

export const STATE: Record<RunState, { label: string; tone: Tone; meaning: string }> = {
  RUNNING: { label: 'Running', tone: 'running', meaning: 'Research and drafting in progress.' },
  DRAFT_READY: {
    label: 'Draft ready',
    tone: 'ready',
    meaning: 'Every claim is backed by evidence. Review and approve.',
  },
  DRAFT_HELD: {
    label: 'Draft held',
    tone: 'held',
    meaning: 'Some sentences still fail a check. Edit them before approving.',
  },
  CONTACT_MOVED: {
    label: 'Contact moved',
    tone: 'clarify',
    meaning: 'This person appears to work somewhere else now.',
  },
  NEEDS_CLARIFICATION: {
    label: 'Needs your pick',
    tone: 'clarify',
    meaning: 'More than one match. Choose the right person to continue.',
  },
  LOW_SIGNAL: {
    label: 'Low signal',
    tone: 'quiet',
    meaning: 'Nothing specific enough to personalise. A generic email would hurt more than help.',
  },
  NOT_A_FIT: { label: 'Not a fit', tone: 'quiet', meaning: 'Outside the ideal customer profile.' },
  NEEDS_REVIEW_SENSITIVE: {
    label: 'Sensitive',
    tone: 'sensitive',
    meaning: 'Only sensitive news was found (layoffs, lawsuits). Not used as a hook.',
  },
  BLOCKED_SUPPRESSED: {
    label: 'Suppressed',
    tone: 'quiet',
    meaning: 'On the do-not-contact list.',
  },
  DUPLICATE: { label: 'Duplicate', tone: 'quiet', meaning: 'Already in this campaign.' },
  RECENTLY_CONTACTED: {
    label: 'Recently contacted',
    tone: 'quiet',
    meaning: 'Contacted too recently to write again.',
  },
  INVALID_INPUT: {
    label: 'Invalid input',
    tone: 'held',
    meaning: 'The prospect or campaign needs fixing first.',
  },
  FAILED: {
    label: 'Failed',
    tone: 'sensitive',
    meaning: 'Free AI capacity ran out mid-run. Research so far is kept; try again shortly.',
  },
}

export const REVIEW: Record<ReviewState, { label: string; tone: Tone }> = {
  APPROVED: { label: 'Approved', tone: 'ready' },
  APPROVED_WITH_EDITS: { label: 'Approved with edits', tone: 'ready' },
  REJECTED: { label: 'Rejected', tone: 'quiet' },
}

export const TONE_CLASS: Record<Tone, string> = {
  ready: 'bg-ready/12 text-ready ring-ready/25',
  held: 'bg-held/12 text-held ring-held/25',
  sensitive: 'bg-sensitive/12 text-sensitive ring-sensitive/25',
  clarify: 'bg-clarify/12 text-clarify ring-clarify/25',
  quiet: 'bg-quiet/12 text-quiet ring-quiet/25',
  running: 'bg-primary/12 text-primary ring-primary/25',
}

export const TONE_DOT: Record<Tone, string> = {
  ready: 'bg-ready',
  held: 'bg-held',
  sensitive: 'bg-sensitive',
  clarify: 'bg-clarify',
  quiet: 'bg-quiet',
  running: 'bg-primary',
}

export function categoryLabel(category: string): string {
  const s = category.replaceAll('_', ' ').replace('mna', 'M&A')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return ''
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 60) return 'just now'
  const units: [number, string][] = [
    [60, 'minute'],
    [3600, 'hour'],
    [86400, 'day'],
  ]
  let unit = units[0]
  for (const u of units) if (seconds >= u[0]) unit = u
  const n = Math.floor(seconds / unit[0])
  return `${n} ${unit[1]}${n === 1 ? '' : 's'} ago`
}

const ROLE_WORK: Record<string, string> = {
  judge: 'planning and scoring',
  writer: 'writing',
  reader: 'reading pages',
  checker: 'checking claims',
}

/** Turn a technical failure into a sentence for the rep, keeping the detail for whoever needs it. */
export function friendly(problem: string): { text: string; detail?: string } {
  const busy = /^All providers failed for role '(\w+)'/.exec(problem)
  if (busy)
    return {
      text: `The free AI models for ${ROLE_WORK[busy[1]] ?? busy[1]} were all busy. Run it again in a minute; search results are cached, so a re-run costs little search quota.`,
      detail: problem,
    }
  return { text: problem }
}
