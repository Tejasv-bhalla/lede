// Server-sent events over fetch, because the browser's EventSource cannot send our access-code
// header. The server replays past events, then follows the run live until it finishes.

import { authHeaders } from './client'
import type { StageEvent } from './types'

export function followRun(
  runId: string,
  onEvent: (e: StageEvent) => void,
  onError: (err: Error) => void,
): () => void {
  const controller = new AbortController()

  void (async () => {
    try {
      const res = await fetch(`/api/runs/${runId}/events`, {
        headers: { ...authHeaders(), Accept: 'text/event-stream' },
        signal: controller.signal,
      })
      if (!res.ok || !res.body) throw new Error(`Live updates unavailable (${res.status})`)
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
      let buffer = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += value
        let split: number
        // Events are separated by a blank line; sse-starlette uses CRLF.
        while ((split = buffer.search(/\r?\n\r?\n/)) !== -1) {
          const block = buffer.slice(0, split)
          buffer = buffer.slice(split).replace(/^\r?\n\r?\n/, '')
          const data = block
            .split(/\r?\n/)
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).trim())
            .join('\n')
          if (data) onEvent(JSON.parse(data) as StageEvent)
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) onError(err as Error)
    }
  })()

  return () => controller.abort()
}
