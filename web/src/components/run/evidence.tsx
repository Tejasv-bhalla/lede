import { ExternalLink } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { Evidence } from '@/api/types'
import { host, when } from '@/lib/evidence'
import { categoryLabel } from '@/lib/status'
import { cn } from '@/lib/utils'

/** The source behind a claim: the exact quote in serif (human words), then where and when. */
export function SourceQuote({ e, className }: { e: Evidence; className?: string }) {
  return (
    <div className={className}>
      <blockquote className="font-serif text-[0.95rem] leading-relaxed">
        “{e.verbatim_quote}”
      </blockquote>
      <a
        href={e.url}
        target="_blank"
        rel="noreferrer"
        className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        {e.publisher || host(e.url)}, {when(e)}
        <ExternalLink className="size-3" />
      </a>
    </div>
  )
}

type Filter = 'all' | 'person' | 'company'
const COLLAPSED = 8 // the facts used in the draft come first

export function EvidenceLedger({ items, used }: { items: Evidence[]; used: Set<string> }) {
  const [filter, setFilter] = useState<Filter>('all')
  const [expanded, setExpanded] = useState(false)
  const shown = useMemo(
    () =>
      items
        .filter((e) => filter === 'all' || e.about === filter)
        .sort((a, b) => Number(used.has(b.id)) - Number(used.has(a.id))),
    [items, filter, used],
  )
  const counts = {
    all: items.length,
    person: items.filter((e) => e.about === 'person').length,
    company: items.filter((e) => e.about === 'company').length,
  }

  return (
    <section aria-labelledby="ledger">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 id="ledger" className="text-base">
          Evidence
        </h2>
        <span className="text-xs text-muted-foreground">{items.length} verified quotes</span>
      </div>
      <div className="mb-3 flex gap-1" role="group" aria-label="Filter evidence">
        {(['all', 'person', 'company'] as const).map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={filter === f}
            onClick={() => setFilter(f)}
            className={cn(
              'rounded-md px-2.5 py-1 text-xs',
              filter === f
                ? 'bg-secondary font-medium'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {f === 'all' ? 'All' : f === 'person' ? 'About them' : 'Their company'} ({counts[f]})
          </button>
        ))}
      </div>
      <ol className="flex flex-col divide-y">
        {(expanded ? shown : shown.slice(0, COLLAPSED)).map((e) => (
          <li key={e.id} id={`evidence-${e.id}`} className="scroll-mt-24 py-3 first:pt-0">
            <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
              <span>{categoryLabel(e.category)}</span>
              {used.has(e.id) && (
                <span className="rounded-sm bg-mark px-1 text-mark-ink">used in draft</span>
              )}
              {e.entailment === 'partial' && (
                <span className="text-held">claim stretches the quote</span>
              )}
              {e.sensitivity !== 'none' && (
                <span className="text-sensitive">sensitive, never a hook</span>
              )}
            </div>
            <p className="text-sm font-medium">{e.claim}</p>
            <SourceQuote e={e} className="mt-1.5 text-muted-foreground" />
          </li>
        ))}
      </ol>
      {shown.length > COLLAPSED && (
        <button
          type="button"
          onClick={() => setExpanded((x) => !x)}
          className="mt-2 text-sm text-primary underline-offset-4 hover:underline"
        >
          {expanded ? 'Show fewer' : `Show all ${shown.length}`}
        </button>
      )}
    </section>
  )
}
