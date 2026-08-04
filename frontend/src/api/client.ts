const TOKEN_KEY = 'dmp.token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

/** An error carrying the problem document the API returns. */
export class ApiError extends Error {
  status: number
  detail: string
  details: (string | { path: string; message: string })[]

  constructor(status: number, title: string, detail: string, details: any[] = []) {
    super(detail || title)
    this.status = status
    this.detail = detail
    this.details = details
  }

  /** Every line worth showing the user, flattened. */
  get lines(): string[] {
    return this.details.map((d) => (typeof d === 'string' ? d : `${d.path}: ${d.message}`))
  }
}

async function parse(response: Response): Promise<any> {
  if (response.status === 204) return null
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers = new Headers(init.headers)
  if (!headers.has('content-type') && init.body) headers.set('content-type', 'application/json')
  if (token) headers.set('authorization', `Bearer ${token}`)

  const response = await fetch(`/api${path}`, { ...init, headers })
  const payload = await parse(response)

  if (!response.ok) {
    if (response.status === 401 && getToken()) {
      setToken(null)
      window.location.href = '/login'
    }
    const detail =
      typeof payload?.detail === 'string'
        ? payload.detail
        : Array.isArray(payload?.detail)
          ? payload.detail.map((d: any) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
          : response.statusText
    throw new ApiError(response.status, payload?.error ?? 'Request failed', detail, payload?.details ?? [])
  }
  return payload as T
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T,>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const out = search.toString()
  return out ? `?${out}` : ''
}
