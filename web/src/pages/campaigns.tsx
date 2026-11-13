import { Plus } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useCampaigns, useProfile } from '@/api/hooks'
import { PageHeader } from '@/components/app-shell'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export function Campaigns() {
  const campaigns = useCampaigns()
  const profile = useProfile()

  return (
    <div className="max-w-4xl">
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
        <Skeleton className="h-32 w-full" />
      ) : !campaigns.data?.length ? (
        <div className="rounded-lg border border-dashed px-8 py-12 text-center">
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
        <ul className="divide-y rounded-lg border bg-card">
          {campaigns.data.map((c) => (
            <li key={c.id}>
              <Link
                to={`/campaigns/${c.id}`}
                className="flex items-center justify-between gap-6 px-5 py-4 hover:bg-accent/50"
              >
                <div className="min-w-0">
                  <p className="font-medium">{c.name}</p>
                  <p className="truncate text-sm text-muted-foreground">{c.objective}</p>
                </div>
                <span className="shrink-0 text-sm text-primary">Open</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
