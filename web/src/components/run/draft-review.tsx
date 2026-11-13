import { CircleAlert, Copy, Mail, UserSearch } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import { useProfile, useReview } from '@/api/hooks'
import type {
  ClaimVerdict,
  Draft,
  Evidence,
  FoundEmail,
  ProspectInput,
  Review,
  RunState,
} from '@/api/types'
import { ReviewBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { writerLabel } from '@/lib/models'
import { emailBody, emailOrigin, gmailComposeUrl, linkedinUrl } from '@/lib/send'

import { SourceQuote } from './evidence'
import { Problem } from './problem'

type Segment =
  | { kind: 'text'; text: string }
  | { kind: 'claim'; text: string; verdict: ClaimVerdict; evidence?: Evidence; n?: number }

/** Same length in, same length out: models mix in non-breaking spaces and odd hyphens, so
 * matching ignores those differences while positions still map onto the original text. */
function comparable(text: string): string {
  return text
    .toLowerCase()
    .replace(/[\u00a0\u2007\u202f\t\n]/g, ' ')
    .replace(/[\u2010-\u2014\u2212]/g, '-')
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201c\u201d]/g, '"')
}

/** Find each checked claim in the email body, in order, without overlaps. */
function segment(body: string, claims: ClaimVerdict[], byId: Map<string, Evidence>): Segment[] {
  const lower = comparable(body)
  const spans = claims
    .map((verdict) => {
      const needle = verdict.claim.trim().replace(/[.!?]+$/, '')
      const start = lower.indexOf(comparable(needle))
      return start < 0 || !needle ? null : { start, end: start + needle.length, verdict }
    })
    .filter((s): s is NonNullable<typeof s> => s !== null)
    .sort((a, b) => a.start - b.start)

  const numbers = new Map<string, number>()
  const out: Segment[] = []
  let cursor = 0
  for (const s of spans) {
    if (s.start < cursor) continue
    if (s.start > cursor) out.push({ kind: 'text', text: body.slice(cursor, s.start) })
    const evidence = s.verdict.evidence_id ? byId.get(s.verdict.evidence_id) : undefined
    if (evidence && !numbers.has(evidence.id)) numbers.set(evidence.id, numbers.size + 1)
    out.push({
      kind: 'claim',
      text: body.slice(s.start, s.end),
      verdict: s.verdict,
      evidence,
      n: evidence ? numbers.get(evidence.id) : undefined,
    })
    cursor = s.end
  }
  if (cursor < body.length) out.push({ kind: 'text', text: body.slice(cursor) })
  return out
}

function ClaimMark({ seg }: { seg: Extract<Segment, { kind: 'claim' }> }) {
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const supported = seg.verdict.verdict === 'supported'
  const show = () => {
    window.clearTimeout(timer.current)
    setOpen(true)
  }
  const hide = () => {
    timer.current = window.setTimeout(() => setOpen(false), 120)
  }

  if (supported && !seg.evidence)
    return (
      <span
        className="underline decoration-primary/60 decoration-dotted decoration-1 underline-offset-4"
        title="Matches one of your approved product claims"
      >
        {seg.text}
      </span>
    )

  if (!supported)
    return (
      <span
        className="underline decoration-destructive decoration-wavy decoration-1 underline-offset-4"
        title={seg.verdict.reason || 'Not supported by the evidence'}
      >
        {seg.text}
      </span>
    )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <span
          role="button"
          tabIndex={0}
          onMouseEnter={show}
          onMouseLeave={hide}
          onFocus={show}
          onBlur={hide}
          className="evidence-mark cursor-help outline-offset-2"
        >
          {seg.text}
        </span>
      </PopoverTrigger>
      <PopoverContent
        className="w-96"
        side="top"
        onMouseEnter={show}
        onMouseLeave={hide}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {seg.evidence && <SourceQuote e={seg.evidence} />}
      </PopoverContent>
    </Popover>
  )
}

export function DraftView({
  draft,
  claims,
  evidence,
}: {
  draft: Draft
  claims: ClaimVerdict[]
  evidence: Evidence[]
}) {
  const byId = useMemo(() => new Map(evidence.map((e) => [e.id, e])), [evidence])
  const segments = useMemo(() => segment(draft.body, claims, byId), [draft.body, claims, byId])

  return (
    <article className="rounded-lg border bg-card px-8 py-7 shadow-[0_1px_0_0_var(--border)]">
      <p className="mb-5 border-b pb-4 text-sm">
        <span className="text-muted-foreground">Subject </span>
        <span className="font-medium">{draft.subject}</span>
      </p>
      <div className="font-serif text-[1.08rem] leading-[1.75] whitespace-pre-wrap">
        {segments.map((s, i) =>
          s.kind === 'text' ? (
            <span key={i}>{s.text}</span>
          ) : (
            <span key={i}>
              <ClaimMark seg={s} />
              {s.n && s.evidence && (
                <a
                  href={`#evidence-${s.evidence.id}`}
                  aria-label={`Source ${s.n}`}
                  className="ml-0.5 align-super font-sans text-[0.65rem] font-semibold text-primary"
                >
                  {s.n}
                </a>
              )}
            </span>
          ),
        )}
      </div>
      {draft.written_by && (
        <p className="mt-6 border-t pt-3 text-xs text-muted-foreground">
          Written by {writerLabel(draft.written_by)}
        </p>
      )}
    </article>
  )
}

/** After approval: the rep sends it from their own Gmail or LinkedIn. Lede sends nothing. */
function SendYourself({
  draft,
  prospect,
  email,
}: {
  draft: Draft
  prospect: ProspectInput
  email: FoundEmail | null
}) {
  const footer = useProfile().data?.footer ?? ''
  const [to, setTo] = useState(email?.address ?? '')
  const text = [
    to.trim() && `To: ${to.trim()}`,
    `Subject: ${draft.subject}`,
    '',
    emailBody(draft, footer),
  ]
    .filter((line, i) => line || i > 0)
    .join('\n')

  async function copy(what: string, value: string) {
    try {
      await navigator.clipboard.writeText(value)
      toast.success(what)
    } catch {
      toast.error('Copying is blocked in this browser', {
        description: 'Select the text and copy it instead.',
      })
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border bg-card px-5 py-4">
      <div>
        <h2 className="text-base">Send it yourself</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Lede never sends email. Open it in your own Gmail or LinkedIn, check it once more and
          press send there. Your footer is added.
        </p>
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="send-to" className="text-sm font-medium">
          To
        </label>
        <Input
          id="send-to"
          type="email"
          placeholder="Their email address"
          value={to}
          onChange={(e) => setTo(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          {email && to.trim() === email.address ? (
            <>
              {emailOrigin(email)}{' '}
              {email.url && (
                <a href={email.url} target="_blank" rel="noreferrer" className="underline">
                  See the page
                </a>
              )}
            </>
          ) : email ? (
            'Changed by you.'
          ) : (
            'No address was found. Type it here if you know it.'
          )}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => copy('Email copied', text)}>
          <Copy className="size-4" /> Copy email
        </Button>
        <Button variant="outline" asChild>
          <a href={gmailComposeUrl(draft, footer, to)} target="_blank" rel="noreferrer">
            <Mail className="size-4" /> Open in Gmail
          </a>
        </Button>
        <Button variant="outline" asChild>
          <a
            href={linkedinUrl(prospect)}
            target="_blank"
            rel="noreferrer"
            onClick={() =>
              void copy('Message copied', emailBody(draft, footer)).then(() =>
                toast.message('Paste it into a LinkedIn message to them.'),
              )
            }
          >
            <UserSearch className="size-4" />{' '}
            {prospect.linkedin_url ? 'Open LinkedIn profile' : 'Find on LinkedIn'}
          </a>
        </Button>
      </div>
    </section>
  )
}

export function DraftReview({
  runId,
  state,
  prospect,
  email,
  draft,
  claims,
  evidence,
  problems,
  review,
}: {
  runId: string
  state: RunState
  prospect: ProspectInput
  email: FoundEmail | null
  draft: Draft
  claims: ClaimVerdict[]
  evidence: Evidence[]
  problems: string[]
  review: Review | null
}) {
  const act = useReview(runId)
  const [editing, setEditing] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)
  const [reason, setReason] = useState('')
  const canApprove = state === 'DRAFT_READY' && !review

  async function send(
    payload: Parameters<typeof act.mutateAsync>[0],
    done: string,
  ): Promise<boolean> {
    try {
      await act.mutateAsync(payload)
      toast.success(done)
      return true
    } catch (err) {
      toast.error('Not saved', { description: (err as Error).message })
      return false
    }
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement
      if (review || editing || rejecting || e.metaKey || e.ctrlKey) return
      if (t.closest('input, textarea, [contenteditable]')) return
      if (e.key === 'a' && canApprove) void send({ action: 'approve' }, 'Draft approved')
      if (e.key === 'e') setEditing(true)
      if (e.key === 'x') setRejecting(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const shown = review?.draft ?? draft

  return (
    <div className="flex flex-col gap-5">
      {review && (
        <div className="flex items-center gap-3 text-sm">
          <ReviewBadge state={review.state} />
          {review.reason && <span className="text-muted-foreground">“{review.reason}”</span>}
        </div>
      )}

      {problems.length > 0 && !review && (
        <div className="rounded-lg border border-held/35 bg-held/8 px-4 py-3 text-sm">
          <p className="flex items-center gap-2 font-medium">
            <CircleAlert className="size-4 text-held" /> Fix these before approving
          </p>
          <ul className="mt-1.5 list-disc pl-6 text-muted-foreground">
            {problems.map((p) => (
              <Problem key={p} problem={p} />
            ))}
          </ul>
        </div>
      )}

      {editing ? (
        <div className="flex flex-col gap-3 rounded-lg border bg-card p-5">
          <Input
            aria-label="Subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          />
          <Textarea
            aria-label="Email"
            value={body}
            rows={9}
            onChange={(e) => setBody(e.target.value)}
            className="font-serif text-[1.02rem] leading-relaxed"
          />
          <p className="text-xs text-muted-foreground">
            Edits are re-checked against this run's rules. New facts you add are your
            responsibility: they are not in the evidence.
          </p>
        </div>
      ) : (
        <DraftView draft={shown} claims={review ? [] : claims} evidence={evidence} />
      )}

      {review && review.state !== 'REJECTED' && (
        <SendYourself draft={shown} prospect={prospect} email={email} />
      )}

      {!review && (
        <div className="sticky bottom-4 z-20 flex items-center justify-between gap-3 rounded-lg border bg-card/95 px-4 py-3 shadow-lg backdrop-blur">
          <p className="text-xs text-muted-foreground">
            {editing
              ? 'Saving approves your edited version.'
              : 'Shortcuts: A approve, E edit, X reject'}
          </p>
          <div className="flex gap-2">
            {editing ? (
              <>
                <Button variant="ghost" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
                <Button
                  disabled={act.isPending}
                  onClick={async () => {
                    if (await send({ action: 'edit', subject, body }, 'Edited draft approved'))
                      setEditing(false)
                  }}
                >
                  Save and approve
                </Button>
              </>
            ) : (
              <>
                <Button variant="ghost" onClick={() => setRejecting(true)}>
                  Reject
                </Button>
                <Button variant="outline" onClick={() => setEditing(true)}>
                  Edit
                </Button>
                <Button
                  disabled={!canApprove || act.isPending}
                  title={canApprove ? undefined : 'Edit the flagged sentences first'}
                  onClick={() => send({ action: 'approve' }, 'Draft approved')}
                >
                  Approve
                </Button>
              </>
            )}
          </div>
        </div>
      )}

      <Dialog open={rejecting} onOpenChange={setRejecting}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject this draft</DialogTitle>
            <DialogDescription>
              Say what was wrong. Reasons are kept to improve future drafts.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            autoFocus
            rows={3}
            placeholder="Wrong person, weak opener, tone…"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejecting(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={!reason.trim() || act.isPending}
              onClick={async () => {
                if (await send({ action: 'reject', reason }, 'Draft rejected')) setRejecting(false)
              }}
            >
              Reject draft
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <p className={cn('sr-only')} aria-live="polite">
        {act.isPending ? 'Saving' : ''}
      </p>
    </div>
  )
}
