import { CheckCircle2, CircleAlert, KeyRound } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useModels, useRemoveKey, useSaveKey, useSaveRoles, useTestModel } from '@/api/hooks'
import type {
  ModelChoice,
  ModelProvider,
  ModelRole,
  ModelSettings,
  ModelTest,
  ProviderId,
} from '@/api/types'
import { PageHeader } from '@/components/app-shell'
import { Field } from '@/components/field'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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

const JOBS: { role: ModelRole; title: string; note: string }[] = [
  {
    role: 'writer',
    title: 'Writing',
    note: 'Writes the email and fixes it when a check fails. The biggest effect on quality.',
  },
  {
    role: 'judge',
    title: 'Judging',
    note: 'Plans the research, confirms who the person is, checks quotes and scores openers.',
  },
  {
    role: 'checker',
    title: 'Fact-checking',
    note: 'Checks each sentence of the draft against the evidence. Best on a different model from writing.',
  },
  {
    role: 'reader',
    title: 'Reading pages',
    note: 'Pulls facts out of every page read, so it makes the most calls. A fast, low-cost model fits.',
  },
]

const FREE = 'free'

export function Models() {
  const { data, isLoading } = useModels()
  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Models"
        description="Every job runs on free models unless you choose your own. Your model goes first, and the free models stay behind it as backup, so a bad key or a spent quota never stops a run."
      />
      {isLoading || !data ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <div className="flex flex-col gap-12">
          {!data.can_save_keys && (
            <Alert>
              <CircleAlert className="size-4" />
              <AlertTitle>Keys can't be saved on this server yet</AlertTitle>
              <AlertDescription>
                Add SETTINGS_SECRET to the server's .env (any long random string) and restart it.
                Keys are encrypted with it before they are stored.
              </AlertDescription>
            </Alert>
          )}
          {/* Remount when saved choices change, so the form starts from them. */}
          <Jobs key={JSON.stringify(data.roles)} data={data} />
          <Keys data={data} />
        </div>
      )}
    </div>
  )
}

// ── which model does each job ────────────────────────────────────────────────

function Jobs({ data }: { data: ModelSettings }) {
  const save = useSaveRoles()
  const [roles, setRoles] = useState(data.roles)
  const withKeys = data.providers.filter((p) => p.has_key)
  const dirty = JSON.stringify(roles) !== JSON.stringify(data.roles)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    try {
      await save.mutateAsync(roles)
      toast.success('Model choices saved', { description: 'New runs use them straight away.' })
    } catch (err) {
      toast.error('The choices were not saved', { description: (err as Error).message })
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div>
        <h2 className="text-base">Jobs</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {withKeys.length
            ? 'Pick a model for any job, or leave it on the free models.'
            : 'Save a key below to choose your own model for a job.'}
        </p>
      </div>
      <ul className="divide-y rounded-lg border bg-card">
        {JOBS.map((job) => (
          <JobRow
            key={job.role}
            job={job}
            choice={roles[job.role]}
            providers={withKeys}
            free={data.free[job.role]}
            onChange={(choice) => setRoles({ ...roles, [job.role]: choice })}
          />
        ))}
      </ul>
      <div className="flex justify-end">
        <Button type="submit" disabled={!dirty || save.isPending}>
          {save.isPending ? 'Saving…' : 'Save model choices'}
        </Button>
      </div>
    </form>
  )
}

function JobRow({
  job,
  choice,
  providers,
  free,
  onChange,
}: {
  job: (typeof JOBS)[number]
  choice: ModelChoice | null
  providers: ModelProvider[]
  free: string[]
  onChange: (choice: ModelChoice | null) => void
}) {
  const test = useTestModel()
  const [result, setResult] = useState<ModelTest | null>(null)
  const provider = providers.find((p) => p.id === choice?.provider)
  const listId = `models-${job.role}`

  return (
    <li className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-6 px-5 py-4">
      <div>
        <p className="font-medium">{job.title}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{job.note}</p>
      </div>
      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-2 gap-2">
          <Select
            value={choice?.provider ?? FREE}
            onValueChange={(v) => {
              setResult(null)
              if (v === FREE) return onChange(null)
              const p = providers.find((x) => x.id === v)
              onChange({ provider: v as ProviderId, model: p?.suggested_models[0] ?? '' })
            }}
          >
            <SelectTrigger aria-label={`${job.title}: provider`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={FREE}>Free models</SelectItem>
              {providers.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {choice ? (
            <>
              <Input
                aria-label={`${job.title}: model`}
                list={listId}
                required
                placeholder="Model name"
                value={choice.model}
                onChange={(e) => {
                  setResult(null)
                  onChange({ ...choice, model: e.target.value })
                }}
              />
              <datalist id={listId}>
                {provider?.suggested_models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </>
          ) : (
            <p
              className="self-center truncate text-sm text-muted-foreground"
              title={free.join(', ')}
            >
              {free.length
                ? free.slice(0, 2).join(', ') + (free.length > 2 ? ' and more' : '')
                : 'None configured'}
            </p>
          )}
        </div>
        {choice && (
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!choice.model.trim() || test.isPending}
              onClick={async () => setResult(await test.mutateAsync(choice))}
            >
              {test.isPending ? 'Testing…' : 'Test'}
            </Button>
            {result ? (
              result.ok ? (
                <span className="flex items-center gap-1 text-ready">
                  <CheckCircle2 className="size-3.5" /> Works (
                  {(result.latency_ms / 1000).toFixed(1)} s)
                </span>
              ) : (
                <span className="text-destructive">{result.error}</span>
              )
            ) : (
              <span>Backup: free models.</span>
            )}
          </div>
        )}
      </div>
    </li>
  )
}

// ── keys ─────────────────────────────────────────────────────────────────────

function Keys({ data }: { data: ModelSettings }) {
  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-base">Your keys</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Keys are encrypted before they are stored and never shown again; only their last four
          characters are, so you can tell which key is saved.
        </p>
      </div>
      <ul className="divide-y rounded-lg border bg-card">
        {data.providers
          .filter((p) => !p.local)
          .map((p) => (
            <KeyRow key={p.id} provider={p} disabled={!data.can_save_keys} />
          ))}
      </ul>
    </section>
  )
}

function KeyRow({ provider, disabled }: { provider: ModelProvider; disabled: boolean }) {
  const save = useSaveKey()
  const remove = useRemoveKey()
  const [key, setKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? '')
  const canSave =
    (key.trim() || provider.key_optional) && (!provider.needs_base_url || baseUrl.trim())

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    try {
      await save.mutateAsync({ provider: provider.id, api_key: key, base_url: baseUrl })
      setKey('')
      toast.success(`${provider.label} key saved`)
    } catch (err) {
      toast.error('The key was not saved', { description: (err as Error).message })
    }
  }

  return (
    <li className="px-5 py-4">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <p className="flex items-center gap-2 font-medium">
            <KeyRound className="size-4 text-muted-foreground" aria-hidden />
            {provider.label}
          </p>
          <span className="text-sm text-muted-foreground">
            {provider.has_key
              ? provider.key_hint
                ? `Saved, ends in ${provider.key_hint}`
                : 'Saved'
              : 'No key'}
          </span>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-end gap-2">
          <div className={provider.needs_base_url ? 'grid grid-cols-2 gap-2' : ''}>
            {provider.needs_base_url && (
              <Field label="Endpoint URL">
                {(id) => (
                  <Input
                    id={id}
                    placeholder="http://localhost:11434/v1"
                    value={baseUrl}
                    disabled={disabled}
                    onChange={(e) => setBaseUrl(e.target.value)}
                  />
                )}
              </Field>
            )}
            <Field label={provider.has_key ? 'Replace key' : 'API key'}>
              {(id) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete="off"
                  placeholder={provider.key_optional ? 'Optional' : ''}
                  value={key}
                  disabled={disabled}
                  onChange={(e) => setKey(e.target.value)}
                />
              )}
            </Field>
          </div>
          <Button type="submit" disabled={disabled || !canSave || save.isPending}>
            Save key
          </Button>
          {provider.has_key && (
            <Button
              type="button"
              variant="ghost"
              disabled={remove.isPending}
              onClick={async () => {
                await remove.mutateAsync(provider.id)
                toast.success(`${provider.label} key removed`, {
                  description: 'Jobs that used it are back on the free models.',
                })
              }}
            >
              Remove
            </Button>
          )}
        </div>
      </form>
    </li>
  )
}
