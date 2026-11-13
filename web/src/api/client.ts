// A small typed client for the FastAPI backend. Every request carries the demo access code.

const CODE_KEY = 'lede.access-code'

export function getAccessCode(): string | null {
  try {
    return localStorage.getItem(CODE_KEY)
  } catch {
    return null
  }
}

export function setAccessCode(code: string | null) {
  try {
    if (code) localStorage.setItem(CODE_KEY, code)
    else localStorage.removeItem(CODE_KEY)
  } catch {
    // storage blocked (private window): the session still works until reload
  }
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(describe(detail) ?? `Request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

function describe(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: [...], msg}]
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = (d.loc ?? []).filter((p) => p !== 'body').join(' → ')
        return field ? `${field}: ${d.msg}` : d.msg
      })
      .join('\n')
  }
  if (detail && typeof detail === 'object' && 'violations' in detail) {
    return (detail as { violations: string[] }).violations.join('\n')
  }
  return null
}

export function authHeaders(): Record<string, string> {
  const code = getAccessCode()
  return code ? { 'X-Access-Code': code } : {}
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData
  const res = await fetch(`/api${path}`, {
    method,
    headers: {
      ...authHeaders(),
      ...(body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  })
  if (res.status === 401) {
    setAccessCode(null)
    window.dispatchEvent(new Event('lede:locked'))
  }
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data)
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
}

/** The access code, when the server is a public demo that shows it on the login page. */
export async function codeHint(): Promise<string | null> {
  try {
    const res = await fetch('/api/auth/hint')
    return res.ok ? ((await res.json()).code as string | null) : null
  } catch {
    return null // no hint is fine; the gate still works
  }
}

export async function checkCode(code: string): Promise<boolean> {
  const res = await fetch('/api/auth/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })
  if (!res.ok) throw new ApiError(res.status, 'The server did not answer. Is the API running?')
  return (await res.json()).ok as boolean
}
