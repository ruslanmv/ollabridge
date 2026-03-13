/** OllaBridge API client — frontend-safe wrappers around backend endpoints. */

const BASE = ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      detail = data?.detail ? ` — ${typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)}` : ''
    } catch {
      // ignore
    }
    throw new Error(`${init?.method || 'GET'} ${path}: ${res.status}${detail}`)
  }
  return res.json()
}

function sanitizeSettingsPatch(patch: Partial<GatewaySettings>): Record<string, unknown> {
  const allowed: (keyof GatewaySettings)[] = [
    'default_model',
    'default_embed_model',
    'ollama_base_url',
    'local_runtime_enabled',
    'homepilot_enabled',
    'homepilot_base_url',
    'homepilot_api_key',
    'homepilot_node_id',
    'homepilot_node_tags',
  ]
  const payload: Record<string, unknown> = {}
  for (const key of allowed) {
    const value = patch[key]
    if (value !== undefined) payload[key] = value
  }
  return payload
}

export type HealthResponse = {
  status: string
  app?: string
  mode: string
  default_model: string
  auth_mode?: string
  relay_enabled?: boolean
  detail?: string
  homepilot_enabled?: boolean
  local_runtime_enabled?: boolean
}

export type Model = {
  id: string
  object: string
  created?: number
  owned_by?: string
}

export type ModelsResponse = {
  object: string
  data: Model[]
}

export type Runtime = {
  node_id: string
  tags: string[]
  capacity: number
  healthy: boolean
  pending?: number
  endpoint?: string
  runtime_base_url?: string
  registered_at?: string
  connector?: string
  meta?: Record<string, unknown>
}

export type RuntimesResponse = {
  runtimes: Runtime[]
  count: number
}

export type RequestLog = {
  id: number
  ts?: string
  timestamp?: number
  model: string
  status?: number
  latency_ms: number
  node_id?: string
  tokens_prompt?: number
  tokens_completion?: number
}

export type RecentResponse = {
  recent?: RequestLog[]
  requests?: RequestLog[]
  total?: number
}

export type PairedDevice = {
  device_id: string
  label: string
  paired_at: string
  last_seen?: string
}

export type PairInfoResponse = {
  pairing_available: boolean
  message?: string
  code_length?: number
  code_ttl?: number
  ttl_remaining?: number
  code_display?: string
  auth_mode?: string
  pairing_enabled?: boolean
  device_count?: number
}

export type PairGenerateResponse = {
  ok: boolean
  code: string
  code_display: string
  ttl: number
  expires_in: number
}

export type PairExchangeResponse = {
  ok: boolean
  device_id: string
  token: string
}

export type DevicesResponse = { devices: PairedDevice[] }
export type RevokeResponse = { ok: boolean; revoked: string }

export type ConnectionInfo = {
  base_url: string
  api_key: string
  api_key_masked: string
  default_model: string
  auth_mode: string
  models: string[]
}

export type GatewaySettings = {
  default_model: string
  default_embed_model: string
  ollama_base_url: string
  local_runtime_enabled: boolean
  homepilot_enabled: boolean
  homepilot_base_url: string
  homepilot_api_key: string
  homepilot_api_key_set?: boolean
  homepilot_node_id: string
  homepilot_node_tags: string
}

export type SettingsUpdateResponse = { ok: boolean; settings: GatewaySettings }

export type SourceKind = 'ollama' | 'homepilot'

export type SourceHealthRequest = {
  source: SourceKind
  base_url: string
  api_key?: string
}

export type SourceHealthResponse = {
  ok: boolean
  source: SourceKind
  reachable: boolean
  status_code?: number
  message: string
  models: string[]
}

export type SourceMode = 'ollama' | 'homepilot' | 'hybrid' | 'none'

export function deriveSourceMode(settings?: Partial<GatewaySettings> | null): SourceMode {
  const ollama = !!settings?.local_runtime_enabled
  const homepilot = !!settings?.homepilot_enabled
  if (ollama && homepilot) return 'hybrid'
  if (ollama) return 'ollama'
  if (homepilot) return 'homepilot'
  return 'none'
}

export type FlowMetricsResponse = {
  active: boolean
  requests_8s: number
  requests_1m: number
  avg_latency_ms_1m: number
  est_prompt_tokens_1m: number
  est_completion_tokens_1m: number
  est_total_tokens_1m: number
  est_tokens_per_sec: number
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  models: () => request<ModelsResponse>('/v1/models'),
  runtimes: () => request<RuntimesResponse>('/admin/runtimes'),
  recent: (limit = 20) => request<RecentResponse>(`/admin/recent?limit=${limit}`),
  flowMetrics: () => request<FlowMetricsResponse>('/admin/flow-metrics'),
  pairInfo: () => request<PairInfoResponse>('/pair/info'),
  pairGenerate: () => request<PairGenerateResponse>('/pair/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }),
  pairExchange: (code: string, label: string) =>
    request<PairExchangeResponse>('/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code, label }) }),
  pairDevices: () => request<DevicesResponse>('/pair/devices'),
  pairRevoke: (device_id: string) =>
    request<RevokeResponse>('/pair/revoke', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id }) }),
  connectionInfo: () => request<ConnectionInfo>('/admin/connection-info'),
  getSettings: () => request<GatewaySettings>('/admin/settings'),
  updateSettings: (patch: Partial<GatewaySettings> | Record<string, unknown>) =>
    request<SettingsUpdateResponse>('/admin/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sanitizeSettingsPatch(patch as Partial<GatewaySettings>)),
    }),
  sourceHealth: (body: SourceHealthRequest) =>
    request<SourceHealthResponse>('/admin/source-health', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}
