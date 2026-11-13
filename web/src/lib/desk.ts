// What is waiting for the rep, worked out once from the run list so the overview, the sidebar
// badge and the campaign pages always agree. Only each prospect's latest run counts: an older
// run that was superseded by a re-run no longer needs anyone.

import { useRuns } from '@/api/hooks'
import type { ProspectInput, ReviewState, RunDetail, RunState } from '@/api/types'

export type ListedRun = RunDetail & {
  prospect: ProspectInput
  review_state: ReviewState | null
  contact_name?: string | null
}

const DRAFTED: RunState[] = ['DRAFT_READY', 'DRAFT_HELD']
const NEEDS_PICK: RunState[] = ['NEEDS_CLARIFICATION', 'CONTACT_MOVED']

export interface Desk {
  latest: ListedRun[] // newest first, one per prospect
  toReview: ListedRun[]
  needsPick: ListedRun[]
  failed: ListedRun[]
  running: ListedRun[]
  count: number // everything the rep should act on
}

export function deskFrom(runs: ListedRun[]): Desk {
  const seen = new Set<number>()
  const latest = runs.filter((r) => !seen.has(r.prospect_id) && seen.add(r.prospect_id))
  const toReview = latest.filter((r) => DRAFTED.includes(r.state) && !r.review_state)
  const needsPick = latest.filter((r) => NEEDS_PICK.includes(r.state))
  const failed = latest.filter((r) => r.state === 'FAILED')
  const running = latest.filter((r) => r.state === 'RUNNING')
  return {
    latest,
    toReview,
    needsPick,
    failed,
    running,
    count: toReview.length + needsPick.length + failed.length,
  }
}

export function useDesk(): Desk & { isLoading: boolean } {
  const runs = useRuns()
  return { ...deskFrom((runs.data ?? []) as ListedRun[]), isLoading: runs.isLoading }
}

/** Who a run writes to, in words: the person, or the company when nobody is chosen yet. */
export function runTitle(r: ListedRun): { who: string; where: string } {
  const person = r.contact_name ?? r.prospect.person_name
  return person
    ? { who: person, where: r.prospect.company_name }
    : { who: r.prospect.company_name, where: 'No contact chosen yet' }
}
