/** OllaBridge API client — binds to existing backend endpoints. */

const BASE = '' // proxied in dev, same-origin in production

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`)
  return res.json()
}

// ── Types ────────────────────────────────────────────────────────────────

export type HealthResponse = {
  status: string
  app: string
  mode: string
  default_model: string
  auth_mode?: string
  relay_enabled?: boolean
}

export type Model = {
  id: string
  object: string
  created: number
  owned_by: string
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
  pending: number
  runtime_base_url: string
  registered_at?: string
}

export type RuntimesResponse = {
  runtimes: Runtime[]
  count: number
}

export type RequestLog = {
  id: number
  timestamp: number
  model: string
  status: number
  latency_ms: number
  node_id: string
  tokens_prompt?: number
  tokens_completion?: number
}

export type RecentResponse = {
  requests: RequestLog[]
  total: number
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

export type DevicesResponse = {
  devices: PairedDevice[]
}

export type RevokeResponse = {
  ok: boolean
  revoked: string
}

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

export type SettingsUpdateResponse = {
  ok: boolean
  settings: GatewaySettings
}

// ── Helpers ──────────────────────────────────────────────────────────────

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`POST ${path}: ${res.status}`)
  return res.json()
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`PUT ${path}: ${res.status}`)
  return res.json()
}

// ── API Functions ────────────────────────────────────────────────────────

export const api = {
  health: () => get<HealthResponse>('/health'),
  models: () => get<ModelsResponse>('/v1/models'),
  runtimes: () => get<RuntimesResponse>('/admin/runtimes'),
  recent: (limit = 20) => get<RecentResponse>(`/admin/recent?limit=${limit}`),
  pairInfo: () => get<PairInfoResponse>('/pair/info'),
  pairGenerate: () => post<PairGenerateResponse>('/pair/generate', {}),
  pairExchange: (code: string, label: string) =>
    post<PairExchangeResponse>('/pair', { code, label }),
  pairDevices: () => get<DevicesResponse>('/pair/devices'),
  pairRevoke: (device_id: string) =>
    post<RevokeResponse>('/pair/revoke', { device_id }),
  connectionInfo: () => get<ConnectionInfo>('/admin/connection-info'),
  getSettings: () => get<GatewaySettings>('/admin/settings'),
  updateSettings: (patch: Partial<GatewaySettings>) =>
    put<SettingsUpdateResponse>('/admin/settings', patch),
}
