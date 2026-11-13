import { Link } from 'react-router-dom'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { useDashboard, useRuns } from '@/api/hooks'
import type { RunState } from '@/api/types'
import { PageHeader } from '@/components/app-shell'
import { StateBadge } from '@/components/status-badge'
import { Skeleton } from '@/components/ui/skeleton'
import { STATE, ago } from '@/lib/status'

const TONE_VAR: Record<string, string> = {
  ready: 'var(--ready)',
  held: 'var(--held)',
  sensitive: 'var(--sensitive)',
  clarify: 'var(--clarify)',
  quiet: 'var(--quiet)',
  running: 'var(--primary)',
}

export function Overview() {
  const board = useDashboard()
  const runs = useRuns()

  if (board.isLoading) return <Skeleton className="h-80 w-full max-w-5xl" />
  const d = board.data
  if (!d) return <p className="text-destructive">{(board.error as Error)?.message}</p>

  const ready = (d.by_state.DRAFT_READY ?? 0) + (d.by_state.DRAFT_HELD ?? 0)
  const outcomes = (Object.entries(d.by_state) as [RunState, number][])
    .map(([state, count]) => ({ state, label: STATE[state].label, count, tone: STATE[state].tone }))
    .sort((a, b) => b.count - a.count)

  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Overview"
        description="Every run ends in an honest state: a draft worth sending, or a clear reason there isn't one."
      />

      {d.runs_total === 0 ? (
        <div className="rounded-lg border border-dashed px-8 py-12 text-center">
          <h2>Nothing has run yet</h2>
          <p className="mx-auto mt-2 max-w-md text-muted-foreground">
            Open a campaign, add a prospect and choose Research and draft. Results show up here.
          </p>
          <Link
            to="/campaigns"
            className="mt-5 inline-block text-primary underline-offset-4 hover:underline"
          >
            Go to campaigns
          </Link>
        </div>
      ) : (
        <>
          <dl className="mb-10 grid grid-cols-4 divide-x rounded-lg border bg-card">
            <Kpi label="Runs" value={d.runs_total} />
            <Kpi label="Drafts written" value={ready} />
            <Kpi
              label="Approved, of reviewed"
              value={
                d.approval_rate === null ? 'None yet' : `${Math.round(d.approval_rate * 100)}%`
              }
            />
            <Kpi
              label="Median run time"
              value={d.median_run_seconds ? `${Math.round(d.median_run_seconds)} s` : '–'}
            />
          </dl>

          <div className="mb-10 grid grid-cols-[1fr_320px] gap-10">
            <section>
              <h2 className="mb-4">How runs ended</h2>
              <div className="h-[220px]">
                <ResponsiveContainer>
                  <BarChart data={outcomes} layout="vertical" margin={{ left: 8, right: 24 }}>
                    <XAxis type="number" allowDecimals={false} hide />
                    <YAxis
                      type="category"
                      dataKey="label"
                      width={130}
                      tickLine={false}
                      axisLine={false}
                      tick={{ fill: 'var(--muted-foreground)', fontSize: 13 }}
                    />
                    <Tooltip
                      cursor={{ fill: 'var(--secondary)' }}
                      contentStyle={{
                        background: 'var(--popover)',
                        border: '1px solid var(--border)',
                        borderRadius: 6,
                        fontSize: 13,
                      }}
                      formatter={(v) => [v, 'Runs']}
                    />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={18}>
                      {outcomes.map((o) => (
                        <Cell key={o.state} fill={TONE_VAR[o.tone]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section>
              <h2 className="mb-1">Search quota this month</h2>
              <p className="mb-4 text-sm text-muted-foreground">
                Paid search engines pause near their free limit; free sources keep working.
              </p>
              <ul className="flex flex-col gap-4">
                {(d.quota ?? []).map((q) => {
                  const share = q.limit ? Math.min(1, q.used / q.limit) : 0
                  return (
                    <li key={q.name}>
                      <div className="mb-1.5 flex justify-between text-sm">
                        <span>{q.name}</span>
                        <span className="text-muted-foreground">
                          {q.unit === 'USD'
                            ? `$${q.used.toFixed(2)} of $${q.limit}`
                            : `${q.used} of ${q.limit} ${q.unit}`}
                        </span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${share * 100}%`,
                            background: share > 0.85 ? 'var(--held)' : 'var(--primary)',
                          }}
                        />
                      </div>
                    </li>
                  )
                })}
              </ul>
            </section>
          </div>

          <section>
            <h2 className="mb-3">Recent runs</h2>
            <ul className="divide-y rounded-lg border bg-card">
              {(runs.data ?? []).slice(0, 8).map((r) => (
                <li key={r.id}>
                  <Link
                    to={`/runs/${r.id}`}
                    className="grid grid-cols-[1fr_180px_140px] items-center gap-4 px-5 py-3 hover:bg-accent/50"
                  >
                    <span className="min-w-0 truncate">
                      <span className="font-medium">
                        {r.prospect.person_name ?? 'Company only'}
                      </span>
                      <span className="text-muted-foreground">, {r.prospect.company_name}</span>
                    </span>
                    <StateBadge state={r.state} className="justify-self-start" />
                    <span className="text-right text-sm text-muted-foreground">
                      {ago(r.finished_at ?? r.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}

function Kpi({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="px-5 py-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold">{value}</dd>
    </div>
  )
}
