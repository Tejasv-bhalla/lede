import { Plus } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useCampaigns, useProfile } from '@/api/hooks'
import type { CampaignListItem } from '@/api/types'
import { PageHeader } from '@/components/app-shell'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ago } from '@/lib/status'
import { cn } from '@/lib/utils'

export function Campaigns() {
  const campaigns = useCampaigns()
  const profile = useProfile()

  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Campaigns"
        description="A campaign is one reason to write to a group of people. Prospects and their drafts live inside it."
        actions={
          <Button asChild>
            <Link to="/setup?step=1">
              <Plus className="size-4" /> New campaign
            </Link>
          </Button>
        }
      />
      {campaigns.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      ) : !campaigns.data?.length ? (
        <div className="rounded-xl border border-dashed px-8 py-14 text-center">
          <h2>No campaigns yet</h2>
          <p className="mx-auto mt-2 max-w-md text-muted-foreground">
            {profile.data
              ? 'Create one to say why you are writing, then add the people to write to.'
              : 'Start with your seller profile; a campaign is checked against it.'}
          </p>
          <Button asChild className="mt-6">
            <Link to={profile.data ? '/setup?step=1' : '/setup'}>
              {profile.data ? 'Create a campaign' : 'Set up your profile'}
            </Link>
          </Button>
        </div>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2">
          {campaigns.data.map((c) => (
            <li key={c.id}>
              <CampaignCard campaign={c} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function CampaignCard({ campaign: c }: { campaign: CampaignListItem }) {
  const s = c.stats
  const done = s.prospects - s.not_run
  // Each prospect's latest outcome, as one bar: approved, waiting on you, other results, not run.
  const waiting = s.to_review + s.needs_you
  const other = Math.max(0, done - waiting - Math.min(s.approved, done))
  const parts = [
    { n: Math.min(s.approved, done), className: 'bg-ready', label: 'approved' },
    { n: waiting, className: 'bg-primary', label: 'waiting for you' },
    { n: other, className: 'bg-quiet/60', label: 'other outcomes' },
  ]

  return (
    <Link
      to={`/campaigns/${c.id}`}
      className="flex h-full flex-col rounded-xl border bg-card px-6 py-5 transition-colors hover:border-primary/40 hover:bg-accent/30"
    >
      <h2 className="truncate">{c.name.trim()}</h2>
      <p className="mt-1 line-clamp-2 min-h-10 text-sm text-muted-foreground">{c.objective}</p>

      <div
        className="mt-5 flex h-2 overflow-hidden rounded-full bg-secondary"
        role="img"
        aria-label={parts.map((p) => `${p.n} ${p.label}`).join(', ')}
      >
        {s.prospects > 0 &&
          parts.map((p) => (
            <span
              key={p.label}
              className={p.className}
              style={{ width: `${(p.n / s.prospects) * 100}%` }}
            />
          ))}
      </div>

      <dl className="mt-4 grid grid-cols-4 gap-2 text-sm">
        <Stat label="Prospects" value={s.prospects} />
        <Stat label="Not run" value={s.not_run} />
        <Stat label="Need you" value={waiting} highlight={waiting > 0} />
        <Stat label="Approved" value={s.approved} />
      </dl>

      <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">
        {s.last_run_at ? `Last run ${ago(s.last_run_at)}` : 'Nothing run yet'}
      </p>
    </Link>
  )
}

function Stat({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('text-lg font-semibold tabular-nums', highlight && 'text-primary')}>
        {value}
      </dd>
    </div>
  )
}
