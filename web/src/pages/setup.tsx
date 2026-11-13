import { AlertTriangle, Check, CircleAlert, Plus, X } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import {
  useCampaign,
  useCampaignCheck,
  useProfile,
  useSaveCampaign,
  useSaveProfile,
} from '@/api/hooks'
import type { Campaign, Persona, SellerProfile, Seniority } from '@/api/types'
import { SIGNAL_CATEGORIES } from '@/api/types'
import { PageHeader } from '@/components/app-shell'
import { Field } from '@/components/field'
import { commas, lines } from '@/lib/forms'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { EMPTY_PROFILE, SAMPLE_CAMPAIGN, SAMPLE_PROFILE } from '@/lib/samples'
import { categoryLabel } from '@/lib/status'
import { cn } from '@/lib/utils'

const STEPS = ['Seller profile', 'Campaign', 'Check the brief'] as const
type Step = 0 | 1 | 2

const SENIORITY: { value: Seniority; label: string }[] = [
  { value: 'ic', label: 'Individual contributor' },
  { value: 'manager', label: 'Manager' },
  { value: 'director', label: 'Director' },
  { value: 'vp', label: 'VP' },
  { value: 'c_level', label: 'C-level' },
]

export function Setup() {
  const [params, setParams] = useSearchParams()
  const step = Number(params.get('step') ?? 0) as Step
  const campaignId = params.get('campaign') ?? undefined
  const go = (s: Step, extra: Record<string, string> = {}) =>
    setParams({ step: String(s), ...(campaignId ? { campaign: campaignId } : {}), ...extra })

  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Set up outreach"
        description="Tell us who you are and what this campaign is for. The two are checked against each other, so a campaign can narrow your profile but never contradict it."
      />
      <ol className="mb-9 flex items-center gap-3" aria-label="Setup steps">
        {STEPS.map((label, i) => (
          <li key={label} className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => (i < step || (i === 1 && step === 0) ? go(i as Step) : undefined)}
              aria-current={i === step ? 'step' : undefined}
              className={cn(
                'flex items-center gap-2 text-sm',
                i === step ? 'font-medium text-foreground' : 'text-muted-foreground',
              )}
            >
              <span
                className={cn(
                  'grid size-6 place-items-center rounded-full border text-xs',
                  i < step && 'border-primary bg-primary text-primary-foreground',
                  i === step && 'border-primary text-primary',
                )}
              >
                {i < step ? <Check className="size-3.5" /> : i + 1}
              </span>
              {label}
            </button>
            {i < STEPS.length - 1 && <span className="h-px w-10 bg-border" aria-hidden />}
          </li>
        ))}
      </ol>

      {step === 0 && <ProfileStep onDone={() => go(1)} />}
      {step === 1 && (
        <CampaignStep campaignId={campaignId} onDone={(id) => go(2, { campaign: id })} />
      )}
      {step === 2 && <CheckStep campaignId={campaignId} onEdit={() => go(1)} />}
    </div>
  )
}

// ── step 1: seller profile ───────────────────────────────────────────────────

function ProfileStep({ onDone }: { onDone: () => void }) {
  const { data, isLoading } = useProfile()
  if (isLoading) return <FormSkeleton />
  return <ProfileForm initial={data} onDone={onDone} />
}

function ProfileForm({ initial, onDone }: { initial?: SellerProfile; onDone: () => void }) {
  const save = useSaveProfile()
  const [p, setP] = useState<SellerProfile>(initial ?? EMPTY_PROFILE)
  const isNew = !initial
  const persona = p.personas[0] ?? EMPTY_PROFILE.personas[0]
  const setPersona = (patch: Partial<Persona>) =>
    setP({ ...p, personas: [{ ...persona, ...patch }, ...p.personas.slice(1)] })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    try {
      await save.mutateAsync(p)
      toast.success('Seller profile saved')
      onDone()
    } catch (err) {
      toast.error('The profile was not saved', { description: (err as Error).message })
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-10">
      {isNew && (
        <div className="flex items-center justify-between gap-4 rounded-lg border border-dashed px-4 py-3 text-sm">
          <span className="text-muted-foreground">
            Trying it out? Fill everything in with a fictional seller.
          </span>
          <Button type="button" variant="outline" size="sm" onClick={() => setP(SAMPLE_PROFILE)}>
            Load the sample
          </Button>
        </div>
      )}

      <Section title="Your company" note="Used to describe you accurately in every email.">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Company name">
            {(id) => (
              <Input
                id={id}
                required
                value={p.company.name}
                onChange={(e) => setP({ ...p, company: { ...p.company, name: e.target.value } })}
              />
            )}
          </Field>
          <Field label="Website domain">
            {(id) => (
              <Input
                id={id}
                required
                placeholder="example.com"
                value={p.company.domain}
                onChange={(e) => setP({ ...p, company: { ...p.company, domain: e.target.value } })}
              />
            )}
          </Field>
        </div>
        <Field label="Product">
          {(id) => (
            <Input
              id={id}
              required
              value={p.offer.product}
              onChange={(e) => setP({ ...p, offer: { ...p.offer, product: e.target.value } })}
            />
          )}
        </Field>
        <Field label="The problem it solves" hint="In your buyer's words, not marketing copy.">
          {(id) => (
            <Textarea
              id={id}
              required
              rows={2}
              value={p.offer.problem_solved}
              onChange={(e) =>
                setP({ ...p, offer: { ...p.offer, problem_solved: e.target.value } })
              }
            />
          )}
        </Field>
      </Section>

      <Section
        title="Who you sell to"
        note="Research looks for signals that matter to this person."
      >
        <Field label="Job titles" hint="Comma-separated, e.g. CFO, VP Finance, Controller.">
          {(id) => (
            <Input
              id={id}
              required
              value={commas.format(persona.title_patterns)}
              onChange={(e) => setPersona({ title_patterns: commas.parse(e.target.value) })}
            />
          )}
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Seniority">
            {(id) => (
              <Select
                value={persona.seniority}
                onValueChange={(v) => setPersona({ seniority: v as Seniority })}
              >
                <SelectTrigger id={id} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SENIORITY.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          <Field label="Best kind of opener" hint="Senior buyers usually respond to company news.">
            {(id) => (
              <Select
                value={persona.hook_preference}
                onValueChange={(v) =>
                  setPersona({ hook_preference: v as Persona['hook_preference'] })
                }
              >
                <SelectTrigger id={id} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="company">Company news</SelectItem>
                  <SelectItem value="individual">Something they said or did</SelectItem>
                </SelectContent>
              </Select>
            )}
          </Field>
        </div>
        <Field label="Their problems you solve" hint="One per line.">
          {(id) => (
            <Textarea
              id={id}
              rows={3}
              value={lines.format(persona.pains)}
              onChange={(e) => setPersona({ pains: lines.parse(e.target.value) })}
            />
          )}
        </Field>
      </Section>

      <Section
        title="What you may say"
        note="Drafts can only make product claims from this list. Anything else is flagged by the fact-check."
      >
        <ClaimsEditor
          claims={p.approved_claims.map((c) => c.text)}
          onChange={(texts) =>
            setP({ ...p, approved_claims: texts.map((text, i) => ({ id: `c${i + 1}`, text })) })
          }
        />
        <Field
          label="Never say"
          hint="One per line. Campaigns can add to this list, never remove from it."
        >
          {(id) => (
            <Textarea
              id={id}
              rows={2}
              value={lines.format(p.never_claims)}
              onChange={(e) => setP({ ...p, never_claims: lines.parse(e.target.value) })}
            />
          )}
        </Field>
      </Section>

      <Section title="Style" note="Applied to every draft.">
        <div className="grid grid-cols-[1fr_160px] gap-4">
          <Field label="Voice">
            {(id) => (
              <Input
                id={id}
                value={p.tone.voice}
                onChange={(e) => setP({ ...p, tone: { ...p.tone, voice: e.target.value } })}
              />
            )}
          </Field>
          <Field label="Word limit">
            {(id) => (
              <Input
                id={id}
                type="number"
                min={40}
                max={200}
                value={p.tone.max_words}
                onChange={(e) =>
                  setP({ ...p, tone: { ...p.tone, max_words: Number(e.target.value) } })
                }
              />
            )}
          </Field>
        </div>
        <Field
          label="Footer"
          hint="Added to exported emails: a way to opt out and your postal address, as anti-spam law requires."
        >
          {(id) => (
            <Input
              id={id}
              value={p.footer}
              onChange={(e) => setP({ ...p, footer: e.target.value })}
            />
          )}
        </Field>
      </Section>

      <div className="flex justify-end border-t pt-6">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save and continue'}
        </Button>
      </div>
    </form>
  )
}

function ClaimsEditor({
  claims,
  onChange,
}: {
  claims: string[]
  onChange: (claims: string[]) => void
}) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium">Approved product claims</span>
      {claims.map((text, i) => (
        <div key={i} className="flex gap-2">
          <Input
            aria-label={`Claim ${i + 1}`}
            value={text}
            onChange={(e) => onChange(claims.map((c, j) => (j === i ? e.target.value : c)))}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove claim ${i + 1}`}
            onClick={() => onChange(claims.filter((_, j) => j !== i))}
          >
            <X className="size-4" />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => onChange([...claims, ''])}
      >
        <Plus className="size-4" /> Add a claim
      </Button>
    </div>
  )
}

// ── step 2: campaign ─────────────────────────────────────────────────────────

function CampaignStep({
  campaignId,
  onDone,
}: {
  campaignId?: string
  onDone: (id: string) => void
}) {
  const profile = useProfile()
  const existing = useCampaign(campaignId ?? '')
  if (profile.isLoading || (campaignId && existing.isLoading)) return <FormSkeleton />
  if (!profile.data)
    return (
      <p className="text-muted-foreground">
        Save a seller profile first: campaigns are checked against it.
      </p>
    )
  return (
    <CampaignForm
      profile={profile.data}
      campaignId={campaignId}
      initial={
        existing.data ?? {
          name: '',
          objective: '',
          signal_priorities: {},
          persona_id: profile.data.personas[0]?.id,
        }
      }
      onDone={onDone}
    />
  )
}

function CampaignForm({
  profile,
  campaignId,
  initial,
  onDone,
}: {
  profile: SellerProfile
  campaignId?: string
  initial: Partial<Campaign>
  onDone: (id: string) => void
}) {
  const save = useSaveCampaign()
  const [c, setC] = useState<Partial<Campaign>>(initial)

  const priorities = c.signal_priorities ?? {}
  const toggle = (cat: (typeof SIGNAL_CATEGORIES)[number]) => {
    const next = { ...priorities }
    if (next[cat] === 'high') delete next[cat]
    else next[cat] = 'high'
    setC({ ...c, signal_priorities: next })
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    try {
      const saved = await save.mutateAsync(c)
      toast.success(campaignId ? 'Campaign saved' : 'Campaign created')
      onDone(saved.id)
    } catch (err) {
      toast.error('The campaign was not saved', { description: (err as Error).message })
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-10">
      {!campaignId && (
        <div className="flex items-center justify-between gap-4 rounded-lg border border-dashed px-4 py-3 text-sm">
          <span className="text-muted-foreground">
            Using the sample seller? Start from its campaign.
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setC({ ...SAMPLE_CAMPAIGN, persona_id: profile.personas[0]?.id })}
          >
            Load the sample
          </Button>
        </div>
      )}
      <Section title="Campaign" note="Why you are writing to these people, now.">
        <Field label="Name">
          {(id) => (
            <Input
              id={id}
              required
              value={c.name ?? ''}
              onChange={(e) => setC({ ...c, name: e.target.value })}
            />
          )}
        </Field>
        <Field
          label="Objective"
          hint="What the email should ask for. Drafts follow it word for word."
        >
          {(id) => (
            <Input
              id={id}
              required
              value={c.objective ?? ''}
              onChange={(e) => setC({ ...c, objective: e.target.value })}
            />
          )}
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Who to write to">
            {(id) => (
              <Select value={c.persona_id} onValueChange={(v) => setC({ ...c, persona_id: v })}>
                <SelectTrigger id={id} className="w-full">
                  <SelectValue placeholder="Choose a buyer" />
                </SelectTrigger>
                <SelectContent>
                  {profile.personas.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.title_patterns.join(', ') || p.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          <Field label="Angle" hint="Optional: the reason now is a good time.">
            {(id) => (
              <Input
                id={id}
                value={c.angle ?? ''}
                onChange={(e) => setC({ ...c, angle: e.target.value })}
              />
            )}
          </Field>
        </div>
      </Section>

      <Section
        title="Signals to look for first"
        note="Research spends its search budget on these before anything else."
      >
        <div className="flex flex-wrap gap-2">
          {SIGNAL_CATEGORIES.map((cat) => {
            const on = priorities[cat] === 'high'
            return (
              <button
                key={cat}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(cat)}
                className={cn(
                  'rounded-full border px-3 py-1 text-sm transition-colors',
                  on
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-input text-muted-foreground hover:text-foreground',
                )}
              >
                {categoryLabel(cat)}
              </button>
            )
          })}
        </div>
      </Section>

      <div className="flex justify-end border-t pt-6">
        <Button type="submit" disabled={save.isPending || !c.persona_id}>
          {save.isPending ? 'Saving…' : 'Save and check'}
        </Button>
      </div>
    </form>
  )
}

// ── step 3: the merged brief ─────────────────────────────────────────────────

function CheckStep({ campaignId, onEdit }: { campaignId?: string; onEdit: () => void }) {
  const navigate = useNavigate()
  const check = useCampaignCheck(campaignId)
  if (!campaignId) return <p className="text-muted-foreground">Save a campaign first.</p>
  if (check.isLoading) return <FormSkeleton />
  if (check.error) return <p className="text-destructive">{(check.error as Error).message}</p>
  const result = check.data!
  const errors = result.issues.filter((i) => i.severity === 'error')

  return (
    <div className="flex flex-col gap-6">
      {result.issues.length === 0 ? (
        <div className="flex items-start gap-3 rounded-lg border border-ready/30 bg-ready/8 px-4 py-3">
          <Check className="mt-0.5 size-4 text-ready" />
          <p className="text-sm">
            The campaign and your profile agree. Every draft will follow both.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-3">
          {result.issues.map((issue) => (
            <li
              key={issue.code + issue.message}
              className={cn(
                'flex gap-3 rounded-lg border px-4 py-3',
                issue.severity === 'error' ? 'border-sensitive/30' : 'border-held/30',
              )}
            >
              {issue.severity === 'error' ? (
                <CircleAlert className="mt-0.5 size-4 shrink-0 text-sensitive" />
              ) : (
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-held" />
              )}
              <div className="text-sm">
                <p>{issue.message}</p>
                <p className="mt-1 text-muted-foreground">{issue.fix}</p>
              </div>
            </li>
          ))}
        </ul>
      )}

      <section>
        <h2 className="mb-3">Where each part of the brief comes from</h2>
        <dl className="grid grid-cols-[180px_1fr] gap-y-2 text-sm">
          {Object.entries(result.provenance).map(([part, source]) => (
            <div key={part} className="contents">
              <dt className="text-muted-foreground">{sentence(part.replaceAll('_', ' '))}</dt>
              <dd>{sentence(source.replace('+', ' and '))}</dd>
            </div>
          ))}
        </dl>
      </section>

      <div className="flex justify-between border-t pt-6">
        <Button variant="outline" onClick={onEdit}>
          Edit the campaign
        </Button>
        <Button disabled={errors.length > 0} onClick={() => navigate(`/campaigns/${campaignId}`)}>
          Add prospects
        </Button>
      </div>
    </div>
  )
}

// ── shared ───────────────────────────────────────────────────────────────────

function Section({
  title,
  note,
  children,
}: {
  title: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <section className="grid grid-cols-[200px_1fr] gap-8">
      <div>
        <h2 className="text-base">{title}</h2>
        {note && <p className="mt-1 text-sm text-muted-foreground">{note}</p>}
      </div>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  )
}

function FormSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-9 w-2/3" />
      <Skeleton className="h-20 w-full" />
    </div>
  )
}

function sentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
