/** Models → Testing: /v1/models/check and /v1/models/checks (api/model_checks_routes.py). */

import { ApiError } from './api'

export type CheckVerdict = 'working' | 'slow' | 'not_working'

export interface ModelCheck {
  model: string
  source: string | null
  verdict: CheckVerdict
  /** The gateway's own error code, or ok / empty_answer / slow / check_timeout. */
  reason_code: string
  /** One sentence for someone who isn't an IT expert. */
  plain: string
  latency_ms: number | null
  http_status: number | null
  /** The technical part (HTTP status and the provider's message, shortened). */
  detail: string | null
  checked_at: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      detail = typeof data?.detail === 'string' ? data.detail : JSON.stringify(data?.detail ?? '')
    } catch {
      // ignore
    }
    throw new ApiError(init?.method || 'GET', path, res.status, detail)
  }
  return res.json()
}

export const modelChecksApi = {
  check: (model: string, signal?: AbortSignal) =>
    request<ModelCheck>('/v1/models/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
      signal,
    }),
  last: () => request<{ items: Record<string, ModelCheck> }>('/v1/models/checks'),
}
