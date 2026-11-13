import { useState } from 'react'

import { checkCode, setAccessCode } from '@/api/client'
import { Wordmark } from '@/components/app-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function AccessGate({ onUnlock }: { onUnlock: () => void }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
            aria-describedby={error ? 'code-error' : undefined}
          />
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
