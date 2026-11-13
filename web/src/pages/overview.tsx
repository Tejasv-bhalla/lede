import { ArrowRight, CheckCircle2, ChevronRight, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useCampaigns, useDashboard } from '@/api/hooks'
import type { QuotaLine, RunState } from '@/api/types'
import { PageHeader } from '@/components/app-shell'
import { ReviewBadge, StateBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { type ListedRun, runTitle, useDesk } from '@/lib/desk'
import { STATE, TONE_DOT, ago } from '@/lib/status'
import { cn } from '@/lib/utils'

export function Overview() {
  const board = useDashboard()
  const desk = useDesk()
  const campaigns = useCampaigns()
  const campaignName = new Map((campaigns.data ?? []).map((c) => [c.id, c.name.trim()]))

  if (board.isLoading || desk.isLoading) return <Skeleton className="h-96 w-full max-w-6xl" />
  const d = board.data
  if (!d) return <p className="text-destructive">{(board.error as Error)?.message}</p>

  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Overview"
        description="Every run ends in an honest state: a draft worth sending, or a clear reason there isn't one."
        actions={
          <Button asChild variant="outline">
            <Link to="/campaigns">
              <Plus className="size-4" /> Add prospects
            </Link>
          </Button>
        }
      />

      {d.runs_total === 0 ? (
        <div className="rounded-xl border border-dashed px-8 py-14 text-center">
          <h2>Nothing has run yet</h2>
          <p className="mx-auto mt-2 max-w-md text-muted-foreground">
            Open a campaign, add a prospect and choose Research. Results show up here.
          </p>
          <Button asChild className="mt-6">
            <Link to="/campaigns">Go to campaigns</Link>
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          <NeedsYou desk={desk} campaignName={campaignName} />
          <Pipeline
            runs={d.runs_total}
            drafts={(d.by_state.DRAFT_READY ?? 0) + (d.by_state.DRAFT_HELD ?? 0)}
            reviewed={Object.values(d.by_review).reduce((a, b) => a + (b ?? 0), 0)}
            approved={(d.by_review.APPROVED ?? 0) + (d.by_review.APPROVED_WITH_EDITS ?? 0)}
            medianSeconds={d.median_run_seconds ?? null}
          />
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
            <Outcomes byState={d.by_state} total={d.runs_total} />
            <Quota lines={d.quota ?? []} />
          </div>
          <RecentRuns runs={desk.latest.slice(0, 8)} campaignName={campaignName} />
        </div>
      )}
    </div>
  )
}

// ── what is waiting for the rep ──────────────────────────────────────────────

function NeedsYou({
  desk,
  campaignName,
}: {
  desk: ReturnType<typeof useDesk>
  campaignName: Map<string, string>
}) {
  if (desk.count === 0)
    return (
      <section className="flex items-center gap-3 rounded-xl border bg-card px-6 py-5">
        <CheckCircle2 className="size-5 text-ready" />
        <div>
          <p className="font-medium">You're all caught up</p>
          <p className="text-sm text-muted-foreground">
            No drafts to review and no runs waiting for you.
            {desk.running.length > 0 &&
              ` ${desk.running.length} still running; they will show up here when done.`}
          </p>
        </div>
      </section>
    )

  const columns = [
    {
      title: 'Drafts to review',
      note: 'Every claim checked against a source',
      runs: desk.toReview,
      action: 'Review',
    },
    {
      title: 'Choose a contact',
      note: 'Unconfirmed, moved or several matches',
      runs: desk.needsPick,
      action: 'Choose',
    },
    {
      title: 'Try again',
      note: 'Free AI capacity ran out mid-run',
      runs: desk.failed,
      action: 'Open',
    },
  ].filter((c) => c.runs.length > 0)

  return (
    <section aria-labelledby="needs-you" className="rounded-xl border bg-card">
      <header className="flex items-baseline justify-between border-b px-6 py-4">
        <h2 id="needs-you">
          Needs you <span className="ml-1 text-muted-foreground">{desk.count}</span>
        </h2>
        <p className="text-sm text-muted-foreground">Nothing is sent without your approval</p>
      </header>
      <div
        className={cn(
          'grid divide-y md:divide-x md:divide-y-0',
          columns.length === 3 && 'md:grid-cols-3',
          columns.length === 2 && 'md:grid-cols-2',
        )}
      >
        {columns.map((c) => (
          <div key={c.title} className="px-6 py-4">
            <p className="font-medium">
              {c.title} <span className="text-muted-foreground">{c.runs.length}</span>
            </p>
            <p className="mb-3 text-xs text-muted-foreground">{c.note}</p>
            <ul className="-mx-2 flex flex-col">
              {c.runs.slice(0, 4).map((r) => {
                const { who, where } = runTitle(r)
                return (
                  <li key={r.id}>
                    <Link
                      to={`/runs/${r.id}`}
                      className="group flex items-center gap-3 rounded-md px-2 py-2 hover:bg-accent"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{who}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {where} · {campaignName.get(r.campaign_id) ?? 'Campaign'}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-0.5 text-xs text-primary opacity-70 group-hover:opacity-100">
                        {c.action}
                        <ChevronRight className="size-3.5" />
                      </span>
                    </Link>
                  </li>
                )
              })}
            </ul>
            {c.runs.length > 4 && (
              <p className="mt-1 text-xs text-muted-foreground">and {c.runs.length - 4} more</p>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

// ── from research to an approved email ───────────────────────────────────────

function Pipeline({
  runs,
  drafts,
  reviewed,
  approved,
  medianSeconds,
}: {
  runs: number
  drafts: number
  reviewed: number
  approved: number
  medianSeconds: number | null
}) {
  const steps = [
    { label: 'Research runs', value: runs, rate: null },
    { label: 'Drafts written', value: drafts, rate: share(drafts, runs, 'of runs') },
    { label: 'Reviewed by you', value: reviewed, rate: share(reviewed, drafts, 'of drafts') },
    { label: 'Approved', value: approved, rate: share(approved, reviewed, 'of reviewed') },
  ]
  return (
    <section aria-label="From research to approved email" className="rounded-xl border bg-card">
      <ol className="grid grid-cols-2 md:grid-cols-4">
        {steps.map((s, i) => (
          <li
            key={s.label}
            className={cn('relative px-6 py-5', i > 0 && 'md:border-l', i % 2 && 'border-l')}
          >
            {i > 0 && (
              <ArrowRight
                aria-hidden
                className="absolute top-1/2 -left-2.5 hidden size-5 -translate-y-1/2 rounded-full border bg-card p-0.5 text-muted-foreground md:block"
              />
            )}
            <p className="text-sm text-muted-foreground">{s.label}</p>
            <p className="mt-1 text-3xl font-semibold tracking-tight">{s.value}</p>
            <p className="mt-1 h-4 text-xs text-muted-foreground">{s.rate}</p>
          </li>
        ))}
      </ol>
      <p className="border-t px-6 py-2.5 text-xs text-muted-foreground">
        {medianSeconds
          ? `A run takes about ${Math.round(medianSeconds)} seconds, research to checked draft.`
          : 'Run times appear after the first finished run.'}
      </p>
    </section>
  )
}

function share(part: number, whole: number, of: string): string | null {
  return whole ? `${Math.round((part / whole) * 100)}% ${of}` : null
}

// ── outcomes and quota ───────────────────────────────────────────────────────

function Outcomes({
  byState,
  total,
}: {
  byState: Partial<Record<RunState, number>>
  total: number
}) {
  const rows = (Object.entries(byState) as [RunState, number][])
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
  const most = rows[0]?.[1] ?? 1
  return (
    <section>
      <h2 className="mb-1">How runs ended</h2>
      <p className="mb-4 text-sm text-muted-foreground">
        A run that writes nothing says why, instead of sending a weak email.
      </p>
      <ul className="flex flex-col gap-2.5">
        {rows.map(([state, n]) => (
          <li
            key={state}
            className="grid grid-cols-[140px_minmax(0,1fr)_64px] items-center gap-3 text-sm"
            title={STATE[state].meaning}
          >
            <span className="truncate">{STATE[state].label}</span>
            <span className="h-2.5 overflow-hidden rounded-full bg-secondary">
              <span
                className={cn('block h-full rounded-full', TONE_DOT[STATE[state].tone])}
                style={{ width: `${(n / most) * 100}%` }}
              />
            </span>
            <span className="text-right tabular-nums">
              {n}
              <span className="ml-1.5 text-xs text-muted-foreground">
                {Math.round((n / total) * 100)}%
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Quota({ lines }: { lines: QuotaLine[] }) {
  return (
    <section>
      <h2 className="mb-1">Free allowance this month</h2>
      <p className="mb-4 text-sm text-muted-foreground">
        Paid services pause near their free limit; free sources keep working.
      </p>
      <ul className="flex flex-col gap-4 rounded-xl border bg-card px-5 py-4">
        {lines.map((q) => {
          const used = q.limit ? Math.min(1, q.used / q.limit) : 0
          return (
            <li key={q.name}>
              <div className="mb-1.5 flex justify-between gap-3 text-sm">
                <span className="font-medium">{q.name}</span>
                <span className="text-muted-foreground tabular-nums">
                  {q.unit === 'USD'
                    ? `$${q.used.toFixed(2)} of $${q.limit}`
                    : `${q.used} of ${q.limit} ${q.unit}`}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
                <div
                  className={cn('h-full rounded-full', used > 0.85 ? 'bg-held' : 'bg-primary')}
                  style={{ width: `${Math.max(used * 100, used ? 2 : 0)}%` }}
                />
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

// ── latest activity ──────────────────────────────────────────────────────────

function RecentRuns({
  runs,
  campaignName,
}: {
  runs: ListedRun[]
  campaignName: Map<string, string>
}) {
  return (
    <section>
      <h2 className="mb-3">Latest activity</h2>
      <ul className="divide-y rounded-xl border bg-card">
        {runs.map((r) => {
          const { who, where } = runTitle(r)
          return (
            <li key={r.id}>
              <Link
                to={`/runs/${r.id}`}
                className="grid grid-cols-[minmax(0,1fr)_180px_170px_110px] items-center gap-4 px-5 py-3 hover:bg-accent/50"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{who}</span>
                  <span className="block truncate text-sm text-muted-foreground">{where}</span>
                </span>
                <span className="truncate text-sm text-muted-foreground">
                  {campaignName.get(r.campaign_id)}
                </span>
                <span>
                  {r.review_state ? (
                    <ReviewBadge state={r.review_state} />
                  ) : (
                    <StateBadge state={r.state} />
                  )}
                </span>
                <span className="text-right text-sm text-muted-foreground">
                  {ago(r.finished_at ?? r.created_at)}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
