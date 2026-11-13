import { ExternalLink, UserRoundCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useStartRun } from '@/api/hooks'
import type { Contact, RunDetail, Tier } from '@/api/types'
import { Button } from '@/components/ui/button'
import { STATE } from '@/lib/status'

import { host } from '@/lib/evidence'

function usePinnedRun(run: RunDetail) {
  const start = useStartRun()
  const navigate = useNavigate()
  return {
    pending: start.isPending,
    go: async (contact: Contact) => {
      try {
        const { run_id } = await start.mutateAsync({
          prospect_id: run.prospect_id,
          tier: run.tier as Tier,
          pinned_identity: contact,
        })
        navigate(`/runs/${run_id}`)
      } catch (err) {
        toast.error('The run did not start', { description: (err as Error).message })
      }
    },
  }
}

/** Ambiguous person, or a company-only prospect: the rep picks who to write to. */
export function ClarificationPicker({ run }: { run: RunDetail }) {
  const pinned = usePinnedRun(run)
  const identity = run.outcome?.identity
  const candidates = identity?.candidates ?? []
  const suggested = identity?.status === 'suggested'

  return (
    <section className="max-w-3xl">
      <h2>{suggested ? 'Who should we write to?' : 'Which of these is your prospect?'}</h2>
      <p className="mt-1 mb-5 text-muted-foreground">
        {suggested
          ? `We found people at ${run.prospect.company_name} who match this campaign's buyer. Pick one and research starts.`
          : 'More than one person matches. Pick the right one so we never write about a stranger.'}
      </p>
      <ul className="grid gap-3 sm:grid-cols-2">
        {candidates.map((c) => (
          <li
            key={`${c.person_name}-${c.company_name}`}
            className="flex flex-col rounded-lg border bg-card p-4"
          >
            <p className="font-medium">{c.person_name}</p>
            <p className="text-sm text-muted-foreground">
              {[c.title, c.company_name].filter(Boolean).join(' at ')}
            </p>
            {c.evidence_quote && (
              <blockquote className="mt-3 font-serif text-sm leading-relaxed">
                “{c.evidence_quote}”
              </blockquote>
            )}
            {c.evidence_url && (
              <a
                href={c.evidence_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1.5 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {host(c.evidence_url)} <ExternalLink className="size-3" />
              </a>
            )}
            <Button
              className="mt-4 self-start"
              size="sm"
              disabled={pinned.pending}
              onClick={() => pinned.go(c)}
            >
              <UserRoundCheck className="size-4" /> Write to {c.person_name?.split(' ')[0]}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The prospect works somewhere else now: show the proof and offer to follow them. */
export function ContactMoved({ run }: { run: RunDetail }) {
  const pinned = usePinnedRun(run)
  const moved = run.outcome?.identity?.contact
  if (!moved) return null
  return (
    <section className="max-w-2xl rounded-lg border bg-card p-6">
      <h2>
        {run.prospect.person_name} has moved to {moved.company_name}
      </h2>
      <p className="mt-1 text-muted-foreground">
        Writing to them about {run.prospect.company_name} would be out of date. Here is what we
        found.
      </p>
      {moved.evidence_quote && (
        <blockquote className="mt-4 border-l-2 border-mark pl-4 font-serif leading-relaxed">
          “{moved.evidence_quote}”
        </blockquote>
      )}
      {moved.evidence_url && (
        <a
          href={moved.evidence_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          {host(moved.evidence_url)} <ExternalLink className="size-3" />
        </a>
      )}
      <div className="mt-5 flex gap-2">
        <Button disabled={pinned.pending} onClick={() => pinned.go(moved)}>
          Research them at {moved.company_name}
        </Button>
      </div>
    </section>
  )
}

/** Runs that end without a draft, on purpose. */
export function NoDraft({ run }: { run: RunDetail }) {
  const meaning = STATE[run.state].meaning
  const problems = run.outcome?.problems ?? []
  return (
    <section className="max-w-2xl rounded-lg border bg-card p-6">
      <h2>No email was written</h2>
      <p className="mt-1 text-muted-foreground">{meaning}</p>
      {problems.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-sm text-muted-foreground">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
