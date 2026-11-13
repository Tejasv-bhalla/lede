import { Check, Circle, LoaderCircle, X } from 'lucide-react'

import { type StageView, type TimedEvent, stageViews } from '@/lib/stages'
import { friendly } from '@/lib/status'
import { cn } from '@/lib/utils'

export function StageTimeline({
  events,
  finished,
  compact = false,
}: {
  events: TimedEvent[]
  finished: boolean
  compact?: boolean
}) {
  const views = stageViews(events, finished)
  return (
    <ol className={cn('flex flex-col', compact ? 'gap-2' : 'gap-0')} aria-label="Run progress">
      {views.map((v, i) => (
        <li key={v.key} className="relative flex gap-3.5">
          {!compact && i < views.length - 1 && (
            <span
              aria-hidden
              className={cn(
                'absolute top-7 left-[11px] h-[calc(100%-1.25rem)] w-px',
                v.status === 'done' ? 'bg-primary/40' : 'bg-border',
              )}
            />
          )}
          <StageIcon status={v.status} />
          <div className={cn('min-w-0 flex-1', !compact && 'pb-6')}>
            <div className="flex items-baseline justify-between gap-3">
              <p
                className={cn(
                  'text-sm',
                  v.status === 'pending' || v.status === 'skipped'
                    ? 'text-muted-foreground'
                    : 'font-medium',
                )}
              >
                {v.label}
              </p>
              {v.seconds !== undefined && (
                <span className="text-xs text-muted-foreground">{v.seconds.toFixed(1)} s</span>
              )}
            </div>
            {v.summary && (
              <p
                className={cn(
                  'mt-0.5 text-sm break-words',
                  v.status === 'failed' ? 'text-destructive' : 'text-muted-foreground',
                )}
              >
                {v.status === 'failed' ? friendly(v.summary).text : v.summary}
              </p>
            )}
            {v.status === 'running' && !compact && v.found.length > 0 && (
              <ul className="mt-3 flex flex-col gap-2" aria-live="polite">
                {v.found.slice(-6).map((claim) => (
                  <li
                    key={claim}
                    className="rounded-md border bg-card px-3 py-2 font-serif text-sm leading-relaxed animate-in fade-in-0 slide-in-from-bottom-1 duration-500"
                  >
                    <span className="evidence-mark">{claim}</span>
                  </li>
                ))}
              </ul>
            )}
            {v.status === 'skipped' && !compact && (
              <p className="mt-0.5 text-xs text-muted-foreground">Not needed for this outcome</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

function StageIcon({ status }: { status: StageView['status'] }) {
  const base = 'relative z-10 grid size-6 shrink-0 place-items-center rounded-full'
  if (status === 'done')
    return (
      <span className={cn(base, 'bg-primary text-primary-foreground')}>
        <Check className="size-3.5" />
      </span>
    )
  if (status === 'running')
    return (
      <span className={cn(base, 'bg-accent text-primary')}>
        <LoaderCircle className="size-4 animate-spin" />
      </span>
    )
  if (status === 'failed')
    return (
      <span className={cn(base, 'bg-destructive/15 text-destructive')}>
        <X className="size-3.5" />
      </span>
    )
  return (
    <span className={cn(base, 'bg-card text-muted-foreground')}>
      <Circle className="size-3" />
    </span>
  )
}
