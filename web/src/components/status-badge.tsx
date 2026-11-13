import type { ReviewState, RunState } from '@/api/types'
import { cn } from '@/lib/utils'
import { REVIEW, STATE, TONE_CLASS, TONE_DOT } from '@/lib/status'

export function StateBadge({ state, className }: { state: RunState; className?: string }) {
  const s = STATE[state]
  return (
    <span
      title={s.meaning}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap',
        TONE_CLASS[s.tone],
        className,
      )}
    >
      <span
        className={cn(
          'size-1.5 rounded-full',
          TONE_DOT[s.tone],
          state === 'RUNNING' && 'animate-pulse',
        )}
      />
      {s.label}
    </span>
  )
}

export function ReviewBadge({ state }: { state: ReviewState }) {
  const r = REVIEW[state]
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset',
        TONE_CLASS[r.tone],
      )}
    >
      {r.label}
    </span>
  )
}
