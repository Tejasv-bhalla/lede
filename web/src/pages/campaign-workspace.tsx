import { Download, FileUp, Play, Plus, Settings2, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import {
  useAddProspect,
  useCampaign,
  useDeleteCampaign,
  useImportCsv,
  useProspects,
  useRuns,
  useStartRun,
} from '@/api/hooks'
import type { CsvPreview, Prospect, ProspectInput, Tier } from '@/api/types'
import { PageHeader } from '@/components/app-shell'
import { Field } from '@/components/field'
import { ReviewBadge, StateBadge } from '@/components/status-badge'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { downloadApproved } from '@/lib/send'
import { ago } from '@/lib/status'
import { cn } from '@/lib/utils'

const TIERS: { value: Tier; label: string; note: string }[] = [
  {
    value: 'quick',
    label: 'Quick',
    note: 'One search round, 6 facts scored. Lightest on free quota.',
  },
  {
    value: 'standard',
    label: 'Standard',
    note: 'Up to three rounds, 12 facts scored. About 2 minutes.',
  },
  { value: 'deep', label: 'Deep', note: 'Up to five rounds, 20 facts scored. For key accounts.' },
]

export function CampaignWorkspace() {
  const { campaignId = '' } = useParams()
  const campaign = useCampaign(campaignId)
  const prospects = useProspects(campaignId)
  const startRun = useStartRun()
  const navigate = useNavigate()
  const [tier, setTier] = useState<Tier>('standard')
  const [adding, setAdding] = useState(false)
  const [importing, setImporting] = useState(false)
  const [deleting, setDeleting] = useState(false)

  // Every approved run counts, not only each prospect's latest: the export includes them all.
  const runs = useRuns({ campaign_id: campaignId })
  const approved = (runs.data ?? []).filter((r) => r.review_state?.startsWith('APPROVED')).length

  async function download() {
    try {
      await downloadApproved(campaignId)
    } catch (err) {
      toast.error('The download failed', { description: (err as Error).message })
    }
  }

  async function run(p: Prospect) {
    try {
      const { run_id } = await startRun.mutateAsync({ prospect_id: p.id, tier })
      navigate(`/runs/${run_id}`)
    } catch (err) {
      toast.error('The run did not start', { description: (err as Error).message })
    }
  }

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={campaign.data?.name ?? 'Campaign'}
        description={campaign.data?.objective}
        actions={
          <>
            <Button
              variant="ghost"
              aria-label="Delete campaign"
              title="Delete campaign"
              onClick={() => setDeleting(true)}
            >
              <Trash2 className="size-4" />
            </Button>
            <Button variant="ghost" asChild>
              <Link to={`/setup?step=1&campaign=${campaignId}`}>
                <Settings2 className="size-4" /> Edit
              </Link>
            </Button>
            <Button
              variant="ghost"
              disabled={!approved}
              title={approved ? undefined : 'Approve a draft first'}
              onClick={download}
            >
              <Download className="size-4" /> Approved drafts{approved ? ` (${approved})` : ''}
            </Button>
            <Button variant="outline" onClick={() => setImporting(true)}>
              <FileUp className="size-4" /> Import CSV
            </Button>
            <Button onClick={() => setAdding(true)}>
              <Plus className="size-4" /> Add prospect
            </Button>
          </>
        }
      />

      <div className="mb-4 flex items-center gap-3 text-sm">
        <span className="text-muted-foreground">Research depth</span>
        <Select value={tier} onValueChange={(v) => setTier(v as Tier)}>
          <SelectTrigger className="w-36" aria-label="Research depth">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TIERS.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-muted-foreground">{TIERS.find((t) => t.value === tier)?.note}</span>
      </div>

      {prospects.isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : !prospects.data?.length ? (
        <div className="rounded-lg border border-dashed px-8 py-12 text-center">
          <h2>No prospects yet</h2>
          <p className="mx-auto mt-2 max-w-md text-muted-foreground">
            Add a person and their company, or just a company and we'll suggest who to write to.
            Have a list? Import a CSV.
          </p>
          <div className="mt-6 flex justify-center gap-2">
            <Button
              variant="ghost"
              disabled={!approved}
              title={approved ? undefined : 'Approve a draft first'}
              onClick={download}
            >
              <Download className="size-4" /> Approved drafts{approved ? ` (${approved})` : ''}
            </Button>
            <Button variant="outline" onClick={() => setImporting(true)}>
              Import CSV
            </Button>
            <Button onClick={() => setAdding(true)}>Add prospect</Button>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-5">Prospect</TableHead>
                <TableHead>Company</TableHead>
                <TableHead>Latest run</TableHead>
                <TableHead>Review</TableHead>
                <TableHead className="pr-5 text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {prospects.data.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="pl-5">
                    <p className="font-medium">
                      {p.person_name ?? (
                        <span className="text-muted-foreground">Anyone suitable</span>
                      )}
                    </p>
                    {p.title && <p className="text-xs text-muted-foreground">{p.title}</p>}
                  </TableCell>
                  <TableCell>
                    <p>{p.company_name}</p>
                    {p.company_domain && (
                      <p className="text-xs text-muted-foreground">{p.company_domain}</p>
                    )}
                  </TableCell>
                  <TableCell>
                    {p.last_run ? (
                      <Link to={`/runs/${p.last_run.id}`} className="flex flex-col gap-1">
                        <StateBadge state={p.last_run.state} />
                        <span className="text-xs text-muted-foreground">
                          {ago(p.last_run.finished_at ?? p.last_run.created_at)}
                        </span>
                      </Link>
                    ) : (
                      <span className="text-sm text-muted-foreground">Not run</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {p.last_run?.review_state && <ReviewBadge state={p.last_run.review_state} />}
                  </TableCell>
                  <TableCell className="pr-5 text-right">
                    {p.last_run?.state === 'RUNNING' ? (
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/runs/${p.last_run.id}`}>Watch</Link>
                      </Button>
                    ) : (
                      <Button
                        variant={p.last_run ? 'outline' : 'default'}
                        size="sm"
                        disabled={startRun.isPending}
                        onClick={() => run(p)}
                      >
                        <Play className="size-3.5" />
                        {p.last_run ? 'Run again' : 'Research and draft'}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <AddProspectDialog campaignId={campaignId} open={adding} onOpenChange={setAdding} />
      <DeleteCampaignDialog
        campaignId={campaignId}
        name={campaign.data?.name ?? 'this campaign'}
        prospects={prospects.data?.length ?? 0}
        runs={runs.data?.length ?? 0}
        approved={approved}
        open={deleting}
        onOpenChange={setDeleting}
      />
      <ImportCsvDialog campaignId={campaignId} open={importing} onOpenChange={setImporting} />
    </div>
  )
}

function DeleteCampaignDialog({
  campaignId,
  name,
  prospects,
  runs,
  approved,
  open,
  onOpenChange,
}: {
  campaignId: string
  name: string
  prospects: number
  runs: number
  approved: number
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const remove = useDeleteCampaign()
  const navigate = useNavigate()
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

  async function confirm() {
    try {
      await remove.mutateAsync(campaignId)
      toast.success(`Deleted ${name}`)
      navigate('/campaigns')
    } catch (err) {
      toast.error('The campaign was not deleted', { description: (err as Error).message })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete {name}?</DialogTitle>
          <DialogDescription>
            This deletes its {plural(prospects, 'prospect')} and {plural(runs, 'run')}, with their
            research and drafts. It can't be undone.
            {approved > 0 &&
              ` ${plural(approved, 'approved draft')} will be lost too; download them first if you still need them.`}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" disabled={remove.isPending} onClick={confirm}>
            {remove.isPending ? 'Deleting…' : 'Delete campaign'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AddProspectDialog({
  campaignId,
  open,
  onOpenChange,
}: {
  campaignId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const add = useAddProspect(campaignId)
  const [p, setP] = useState<ProspectInput>({ company_name: '' })
  const set = (k: keyof ProspectInput) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setP({ ...p, [k]: e.target.value || null })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    try {
      await add.mutateAsync(p)
      toast.success(`Added ${p.person_name ?? p.company_name}`)
      setP({ company_name: '' })
      onOpenChange(false)
    } catch (err) {
      toast.error('The prospect was not added', { description: (err as Error).message })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Add a prospect</DialogTitle>
            <DialogDescription>
              Leave the person blank to have us suggest someone at the company who fits this
              campaign; you confirm before any research runs.
            </DialogDescription>
          </DialogHeader>
          <div className="my-5 grid grid-cols-2 gap-4">
            <Field label="Company" className="col-span-2">
              {(id) => (
                <Input id={id} required value={p.company_name} onChange={set('company_name')} />
              )}
            </Field>
            <Field label="Person (optional)">
              {(id) => <Input id={id} value={p.person_name ?? ''} onChange={set('person_name')} />}
            </Field>
            <Field label="Title (optional)">
              {(id) => <Input id={id} value={p.title ?? ''} onChange={set('title')} />}
            </Field>
            <Field
              label="Company website (optional)"
              className="col-span-2"
              hint="Makes sure we research the right company."
            >
              {(id) => (
                <Input
                  id={id}
                  placeholder="acme.com"
                  value={p.company_domain ?? ''}
                  onChange={set('company_domain')}
                />
              )}
            </Field>
            <Field
              label="Email (optional)"
              className="col-span-2"
              hint="Leave blank and we look for it once a draft is written."
            >
              {(id) => (
                <Input
                  id={id}
                  type="email"
                  placeholder="priya@acme.com"
                  value={p.email ?? ''}
                  onChange={set('email')}
                />
              )}
            </Field>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!p.company_name.trim() || add.isPending}>
              Add prospect
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

const CSV_TEMPLATE =
  'Full name,Company,Website,Job title,Email,Notes\nPriya Shah,Acme,acme.com,VP Finance,,Met at FinOps Summit\n,Initech,initech.com,,,\n'

function ImportCsvDialog({
  campaignId,
  open,
  onOpenChange,
}: {
  campaignId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const importCsv = useImportCsv(campaignId)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CsvPreview | null>(null)
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  function reset() {
    setFile(null)
    setPreview(null)
    importCsv.reset()
  }

  async function choose(f: File) {
    setFile(f)
    try {
      setPreview(await importCsv.mutateAsync({ file: f, dryRun: true }))
    } catch {
      setPreview(null)
    }
  }

  async function confirm() {
    if (!file) return
    try {
      const result = await importCsv.mutateAsync({ file, dryRun: false })
      toast.success(`Imported ${result.saved} prospect${result.saved === 1 ? '' : 's'}`)
      reset()
      onOpenChange(false)
    } catch (err) {
      toast.error('The import failed', { description: (err as Error).message })
    }
  }

  const template = `data:text/csv;charset=utf-8,${encodeURIComponent(CSV_TEMPLATE)}`

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset()
        onOpenChange(o)
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import prospects from a CSV</DialogTitle>
          <DialogDescription>
            Nothing is saved or spent until you confirm. We need a company column; names, titles,
            websites and notes are optional.{' '}
            <a
              href={template}
              download="prospects-template.csv"
              className="text-primary underline-offset-4 hover:underline"
            >
              Download a template
            </a>
            .
          </DialogDescription>
        </DialogHeader>

        {!preview ? (
          <button
            type="button"
            onClick={() => input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              const f = e.dataTransfer.files[0]
              if (f) void choose(f)
            }}
            className={cn(
              'my-4 grid h-40 place-items-center rounded-lg border border-dashed text-sm text-muted-foreground transition-colors',
              dragging && 'border-primary bg-accent text-foreground',
            )}
          >
            {importCsv.isPending
              ? 'Reading the file…'
              : importCsv.error
                ? (importCsv.error as Error).message
                : 'Drop a CSV here, or choose a file'}
          </button>
        ) : (
          <div className="my-4 flex flex-col gap-4 text-sm">
            <p>
              <span className="font-medium">{preview.rows.length}</span> prospect
              {preview.rows.length === 1 ? '' : 's'} ready to import from {file?.name}.
              {preview.unmapped_columns.length > 0 &&
                ` Ignored columns: ${preview.unmapped_columns.join(', ')}.`}
            </p>
            <div className="max-h-56 overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Person</TableHead>
                    <TableHead>Company</TableHead>
                    <TableHead>Website</TableHead>
                    <TableHead>Email</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.rows.map((r, i) => (
                    <TableRow key={i}>
                      <TableCell>
                        {r.person_name ?? (
                          <span className="text-muted-foreground">We'll suggest someone</span>
                        )}
                      </TableCell>
                      <TableCell>{r.company_name}</TableCell>
                      <TableCell className="text-muted-foreground">{r.company_domain}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {r.email ?? (r.person_name ? "We'll look for it" : '')}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {preview.errors.length > 0 && (
              <div>
                <p className="mb-1.5 font-medium">
                  {preview.errors.length} row{preview.errors.length === 1 ? '' : 's'} will be
                  skipped
                </p>
                <ul className="text-muted-foreground">
                  {preview.errors.map((e) => (
                    <li key={e.row}>
                      Row {e.row}: {e.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void choose(f)
            e.target.value = ''
          }}
        />
        <DialogFooter>
          {preview && (
            <Button variant="ghost" onClick={reset}>
              Choose another file
            </Button>
          )}
          <Button disabled={!preview?.rows.length || importCsv.isPending} onClick={confirm}>
            Import {preview?.rows.length ?? ''} prospect{preview?.rows.length === 1 ? '' : 's'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
