import type { Evidence } from '@/api/types'

export function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function when(e: Evidence): string {
  const d = e.event_date ?? e.published_at
  return d
    ? new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    : 'Undated'
}
