import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { keys, useRun } from '@/api/hooks'
import { followRun } from '@/api/sse'
import type { RunDetail } from '@/api/types'
import { PageHeader } from '@/components/app-shell'
import { DraftReview } from '@/components/run/draft-review'
import { EvidenceLedger } from '@/components/run/evidence'
import { HookScoreboard } from '@/components/run/hook-scoreboard'
import { ClarificationPicker, ContactMoved, NoDraft } from '@/components/run/outcome-panels'
import { StageTimeline } from '@/components/run/stage-timeline'
import type { TimedEvent } from '@/lib/stages'
import { cn } from '@/lib/utils'
import { StateBadge } from '@/components/status-badge'
import { Skeleton } from '@/components/ui/skeleton'

export function RunPage() {
  const { runId = '' } = useParams()
  const run = useRun(runId)

  if (run.isLoading) return <Skeleton className="h-96 w-full max-w-6xl" />
  if (run.error || !run.data)
    return (
      <p className="text-destructive">
        This run could not be loaded: {(run.error as Error | null)?.message ?? 'not found'}.
      </p>
    )
  return <RunView run={run.data} />
}

function RunView({ run }: { run: RunDetail }) {
  const live = useLiveEvents(run)
  const finished = run.state !== 'RUNNING'
  const who = run.prospect.person_name ?? `Someone at ${run.prospect.company_name}`

  return (
    <div className="max-w-[1400px]">
      <Link
        to={`/campaigns/${run.campaign_id}`}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> Campaign
      </Link>
      <PageHeader
        title={who}
        description={[run.prospect.title, run.prospect.company_name].filter(Boolean).join(', ')}
        actions={<StateBadge state={run.state} />}
      />

      {!finished ? (
        <div className="grid max-w-3xl gap-6">
          <p className="text-muted-foreground">
            Researching public sources, checking every quote against its page, then drafting. A
            standard run takes about two minutes on free AI capacity.
          </p>
          <StageTimeline events={live} finished={false} />
        </div>
      ) : (
        <FinishedRun run={run} events={live} />
      )}
    </div>
  )
}

function FinishedRun({ run, events }: { run: RunDetail; events: TimedEvent[] }) {
  const outcome = run.outcome
  const ledger = outcome?.research?.ledger ?? []
  const used = useMemo(
    () =>
      new Set([
        ...(outcome?.draft?.citations ?? []),
        ...(outcome?.claims ?? []).map((c) => c.evidence_id).filter((x): x is string => Boolean(x)),
      ]),
    [outcome],
  )
  const research = outcome?.research

  const main = (() => {
    if (run.state === 'NEEDS_CLARIFICATION') return <ClarificationPicker run={run} />
    if (run.state === 'CONTACT_MOVED') return <ContactMoved run={run} />
    if (outcome?.draft)
      return (
        <DraftReview
          runId={run.id}
          state={run.state}
          draft={outcome.draft}
          claims={outcome.claims ?? []}
          evidence={ledger}
          problems={outcome.problems}
          review={run.review}
        />
      )
    return <NoDraft run={run} />
  })()

  const hasDraft = Boolean(outcome?.draft)
  return (
    <div
      className={cn(
        'grid gap-8 max-xl:grid-cols-[minmax(0,1fr)_300px]',
        // The right-hand scoreboard only exists with a draft; otherwise the panel takes its room.
        hasDraft
          ? 'grid-cols-[minmax(260px,320px)_minmax(0,1fr)_minmax(260px,320px)]'
          : 'grid-cols-[minmax(260px,320px)_minmax(0,1fr)]',
      )}
    >
      <aside className="flex flex-col gap-8 max-xl:order-2">
        <section>
          <h2 className="mb-3 text-base">How it went</h2>
          <StageTimeline events={events} finished compact />
          {research && (
            <p className="mt-4 text-xs text-muted-foreground">
              {research.searches_used} searches, {research.pages_used} pages read,{' '}
              {research.rejected.length} quotes rejected because they were not on the page,{' '}
              {research.failures.length} sources unavailable.
            </p>
          )}
        </section>
        {ledger.length > 0 && <EvidenceLedger items={ledger} used={used} />}
      </aside>
      <div className="min-w-0 max-xl:order-1">{main}</div>
      {hasDraft && outcome?.ranking && (
        <aside className="max-xl:order-3">
          <HookScoreboard
            ranked={outcome.ranking.ranked}
            vetoed={outcome.ranking.vetoed}
            chosenId={outcome.draft?.citations[0]}
          />
        </aside>
      )}
    </div>
  )
}

/** Follow a running run's events; when it finishes, reload its full detail. Finished runs show
 * their saved events. */
function useLiveEvents(run: RunDetail): TimedEvent[] {
  const qc = useQueryClient()
  const [live, setLive] = useState<{ runId: string; events: TimedEvent[] }>({
    runId: run.id,
    events: [],
  })
  const running = run.state === 'RUNNING'

  useEffect(() => {
    if (!running) return
    return followRun(
      run.id,
      (e) => {
        setLive((prev) => ({
          runId: run.id,
          events: [...(prev.runId === run.id ? prev.events : []), { ...e, at: Date.now() }],
        }))
        if (e.stage === 'run' && e.status === 'finished') {
          void qc.invalidateQueries({ queryKey: keys.run(run.id) })
          void qc.invalidateQueries({ queryKey: ['campaigns'] })
        }
      },
      () => void qc.invalidateQueries({ queryKey: keys.run(run.id) }),
    )
  }, [run.id, running, qc])

  if (live.runId === run.id && live.events.length) {
    // Keep the timing measured live, even after the run's saved detail arrives.
    return running || live.events.some((e) => e.stage === 'run') ? live.events : run.events
  }
  return run.events
}
