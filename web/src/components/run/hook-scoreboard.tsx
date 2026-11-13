import type { Evidence, RankedHook } from '@/api/types'
import { categoryLabel } from '@/lib/status'

const DIMENSIONS: [string, string][] = [
  ['offer_relevance', 'Fits your offer'],
  ['specificity', 'Specific to them'],
  ['recency', 'Recent'],
  ['persona_fit', 'Suits their role'],
  ['source_strength', 'Strong source'],
  ['closeness', 'Close to the person'],
]

const VETO: Record<string, string> = {
  sensitive: 'Sensitive news is never used as an opener',
  entity_not_confirmed: 'Might be about a different person or company',
  quote_not_verified: 'Quote not found on the page',
  claim_not_supported: "The quote doesn't support the claim",
  unscored: 'Not shortlisted for scoring',
}

export function HookScoreboard({
  ranked,
  vetoed,
  chosenId,
}: {
  ranked: RankedHook[]
  vetoed: { evidence: Evidence; reason: string }[]
  chosenId?: string
}) {
  const blocked = vetoed.filter((v) => v.reason !== 'unscored')
  return (
    <section aria-labelledby="scores" className="flex flex-col gap-6">
      <div>
        <h2 id="scores" className="mb-1 text-base">
          Why this opener
        </h2>
        <p className="text-xs text-muted-foreground">
          Each candidate is scored twice from 1 to 5 on six questions; your weights decide the
          total.
        </p>
      </div>
      <ol className="flex flex-col gap-5">
        {ranked.slice(0, 3).map((h, i) => (
          <li key={h.evidence.id}>
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <p className="text-sm font-medium">
                {i === 0 ? 'Chosen' : `Alternative ${i}`}
                {h.evidence.id === chosenId && i !== 0 && ' (used)'}
              </p>
              <span className="text-sm font-semibold">{h.total.toFixed(1)}</span>
            </div>
            <p className="mb-2.5 text-sm text-muted-foreground">
              <span className="text-foreground/80">{categoryLabel(h.evidence.category)}:</span>{' '}
              {h.evidence.claim}
            </p>
            <dl className="grid grid-cols-[1fr_88px] gap-x-3 gap-y-1">
              {DIMENSIONS.map(([key, label]) => {
                const score = h.dimension_scores[key] ?? 0
                return (
                  <div key={key} className="contents">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="flex items-center gap-1.5" aria-label={`${score} out of 5`}>
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
                        <span
                          className="block h-full rounded-full bg-primary"
                          style={{ width: `${(score / 5) * 100}%` }}
                        />
                      </span>
                      <span className="w-6 text-right text-xs">{score.toFixed(1)}</span>
                    </dd>
                  </div>
                )
              })}
            </dl>
            {(h.reasons.overall ?? Object.values(h.reasons)[0]) && (
              <p className="mt-2 text-xs text-muted-foreground">
                {h.reasons.overall ?? Object.values(h.reasons)[0]}
              </p>
            )}
          </li>
        ))}
      </ol>
      {blocked.length > 0 && (
        <div>
          <h3 className="mb-2">Left out on purpose</h3>
          <ul className="flex flex-col gap-2">
            {blocked.slice(0, 6).map((v) => (
              <li key={v.evidence.id} className="text-xs">
                <p className="text-foreground/80">{v.evidence.claim}</p>
                <p className="text-muted-foreground">{VETO[v.reason] ?? v.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
