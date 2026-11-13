import { useEffect, useState } from 'react'

import { checkCode, codeHint, setAccessCode } from '@/api/client'
import { Wordmark } from '@/components/app-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function AccessGate({ onUnlock }: { onUnlock: () => void }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState<string | null>(null)

  useEffect(() => {
    void codeHint().then(setHint)
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (await checkCode(code.trim())) {
        setAccessCode(code.trim())
        onUnlock()
      } else {
        setError('That code is not right. Check the code you were given and try again.')
      }
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-svh place-items-center px-6">
      <div className="w-full max-w-sm">
        <Wordmark className="mb-10 text-base" />
        <h1 className="font-serif text-[2rem] font-medium leading-tight">
          Every sentence, backed by a source.
        </h1>
        <p className="mt-3 text-muted-foreground">
          Research a prospect, find something real to say, and get a first email where each claim
          links to the page it came from.
        </p>
        <form onSubmit={submit} className="mt-9 flex flex-col gap-3">
          <Label htmlFor="code">Access code</Label>
          <Input
            id="code"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value)}
            aria-invalid={Boolean(error)}
            aria-describedby={
              [error && 'code-error', hint && 'code-hint'].filter(Boolean).join(' ') || undefined
            }
          />
          {hint && (
            <p id="code-hint" className="text-sm text-muted-foreground">
              Reviewing this demo? The access code is{' '}
              <button
                type="button"
                onClick={() => setCode(hint)}
                className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[0.85em] text-foreground hover:bg-accent"
                title="Fill it in"
              >
                {hint}
              </button>
            </p>
          )}
          {error && (
            <p id="code-error" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" disabled={!code.trim() || busy} className="mt-1">
            {busy ? 'Checking…' : 'Open'}
          </Button>
        </form>
      </div>
    </div>
  )
}
