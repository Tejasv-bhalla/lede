import type { StageEvent } from '@/api/types'

export const STAGES = [
  { key: 'identity', label: 'Confirm who they are' },
  { key: 'research', label: 'Research' },
  { key: 'verify', label: 'Check each claim against its quote' },
  { key: 'score', label: 'Score the best openers' },
  { key: 'draft', label: 'Write two drafts, keep the better' },
  { key: 'fact_check', label: 'Fact-check sentence by sentence' },
  { key: 'email', label: 'Find their email' },
] as const

export type TimedEvent = StageEvent & { at?: number }

export type StageView = {
  key: string
  label: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  summary: string
  seconds?: number
  found: string[] // facts reported while the stage ran, newest last
}

export function stageViews(events: TimedEvent[], finished: boolean): StageView[] {
  return STAGES.map(({ key, label }) => {
    const mine = events.filter((e) => e.stage === key)
    const started = mine.find((e) => e.status === 'started')
    const ended = mine.find((e) => e.status === 'done' || e.status === 'failed')
    const progress = mine.filter((e) => e.status === 'progress')
    const found = progress.flatMap((e) => e.items ?? [])
    const seconds = started?.at && ended?.at ? (ended.at - started.at) / 1000 : undefined
    if (ended)
      return {
        key,
        label,
        status: ended.status as 'done' | 'failed',
        summary: ended.summary,
        seconds,
        found,
      }
    if (started)
      return {
        key,
        label,
        status: finished ? 'failed' : 'running',
        summary: progress.at(-1)?.summary ?? '',
        found,
      }
    return { key, label, status: finished ? 'skipped' : 'pending', summary: '', found }
  })
}
