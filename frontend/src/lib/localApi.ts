/**
 * OllaBridge local-catalog API client.
 *
 * Typed wrappers around the /local/* endpoints exposed by
 * `src/ollabridge/addons/local_catalog/routes.py`.
 *
 * Mirrors the conventions in ./api.ts:
 *   - throw on non-2xx with a useful detail string
 *   - JSON in, JSON out
 *   - X-API-Key header injected so the gateway's `require_api_key`
 *     dependency passes (same key the rest of the SPA uses).
 */

const BASE = ''

function apiKey(): string {
  // The SPA picks up an API key from the session cookie or settings;
  // ./api.ts already handles wiring. Re-use the same helper if you have
  // one; this stub falls back to a localStorage entry.
  try {
    return localStorage.getItem('ollabridge.apiKey') || ''
  } catch {
    return ''
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) || {}),
  }
  const k = apiKey()
  if (k) headers['X-API-Key'] = k

  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      detail = data?.detail
        ? ` — ${typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)}`
        : ''
    } catch {
      // ignore
    }
    throw new Error(`${init?.method || 'GET'} ${path}: ${res.status}${detail}`)
  }
  return res.json()
}

// ── Types ─────────────────────────────────────────────────────────────

export type LocalSetupStatus =
  | 'auto'
  | 'verified'
  | 'broken'
  | 'not_installed'
  | 'pulling'
  | 'disabled'
  | 'removed'

export type LocalRuntimeKind =
  | 'ollama'
  | 'llamacpp'
  | 'vllm'
  | 'openai_compatible'
  | 'unknown'

export type LocalCapabilities = {
  supports_chat: boolean
  supports_embeddings: boolean
  supports_tools: boolean
  supports_vision: boolean
  supports_structured_output: boolean
  supports_streaming: boolean
}

export type LocalModel = {
  router_model_id: string
  node_id: string
  runtime: LocalRuntimeKind
  external_model_id: string
  display_name: string | null
  family: string | null
  parameter_size: string | null
  parameter_count: number | null
  quantization: string | null
  context_window: number | null
  disk_size_bytes: number | null
  size_marker: 'tiny' | 'small' | 'medium' | 'large' | 'huge' | 'unknown'
  capabilities: LocalCapabilities | null
  rank: number
  score: number
  is_top_recommended: boolean
  enabled: boolean
  pinned: boolean
  manually_added: boolean
  setup_status: LocalSetupStatus
  modified_at: string | null
  last_seen_at: string | null
  last_checked_at: string | null
  last_error: string | null
  latency_observed_ms: number | null
  avg_latency_ms: number | null
}

export type LocalCatalogStats = {
  node_id: string | null
  total: number
  enabled: number
  top_recommended: number
  pinned: number
  manual: number
  verified: number
  broken: number
  removed: number
  last_sync_at: string | null
  last_sync_ok: boolean | null
  total_disk_bytes: number
}

export type LocalRuntimeInfo = {
  node_id: string
  node_name: string
  runtime: LocalRuntimeKind
  runtime_base_url: string
  reachable: boolean
  stats: LocalCatalogStats
  capabilities: {
    chat: boolean
    embeddings: boolean
    streaming: boolean
    tools: boolean
  }
}

export type LocalModelsResponse = {
  models: LocalModel[]
  stats: LocalCatalogStats
  nodes: string[]
}

export type LocalSyncResult = {
  node_id: string
  started_at: string
  finished_at: string
  fetched: number
  upserted: number
  promoted_to_top: number
  demoted_from_top: number
  marked_removed: number
  aliases_written: number
  error: string | null
}

export type LocalPullProgress = {
  node_id: string
  external_model_id: string
  status: 'queued' | 'running' | 'completed' | 'error'
  total_bytes: number
  completed_bytes: number
  progress_pct: number
  error: string | null
  last_update?: string
}

export type LocalActivePullsResponse = {
  pulls: LocalPullProgress[]
}

export type LocalCloudManifest = {
  node: {
    id: string
    name: string
    runtime: LocalRuntimeKind
    runtime_base_url: string
    execution_location: 'local'
  }
  stats: LocalCatalogStats
  models: LocalModel[]
}

// ── Calls ─────────────────────────────────────────────────────────────

export const localApi = {
  runtimeInfo: () => request<LocalRuntimeInfo>('/local/runtime/info'),

  listModels: (params: {
    nodeId?: string
    enabled?: boolean
    top?: boolean
    family?: string
    limit?: number
  } = {}) => {
    const qs = new URLSearchParams()
    if (params.nodeId) qs.set('node_id', params.nodeId)
    if (params.enabled !== undefined) qs.set('enabled', String(params.enabled))
    if (params.top !== undefined) qs.set('top', String(params.top))
    if (params.family) qs.set('family', params.family)
    if (params.limit) qs.set('limit', String(params.limit))
    const q = qs.toString()
    return request<LocalModelsResponse>(`/local/models${q ? `?${q}` : ''}`)
  },

  topModels: (nodeId?: string, limit = 3) => {
    const qs = new URLSearchParams()
    if (nodeId) qs.set('node_id', nodeId)
    qs.set('limit', String(limit))
    return request<{ models: LocalModel[] }>(`/local/models/top?${qs}`)
  },

  sync: (body: { node_id?: string; auto_enable?: number } = {}) =>
    request<LocalSyncResult>('/local/models/sync', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  manualAdd: (body: {
    node_id: string
    external_model_id: string
    runtime?: string
    display_name?: string
    enabled?: boolean
    pinned?: boolean
    supports_tools?: boolean
    supports_vision?: boolean
    supports_embeddings?: boolean
  }) =>
    request<LocalModel>('/local/models/manual', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  enable: (routerModelId: string, enabled: boolean) =>
    request<{ ok: boolean }>(
      `/local/models/${encodeURI(routerModelId)}/enable`,
      { method: 'POST', body: JSON.stringify({ enabled }) }
    ),

  pin: (routerModelId: string, pinned: boolean) =>
    request<{ ok: boolean }>(
      `/local/models/${encodeURI(routerModelId)}/pin`,
      { method: 'POST', body: JSON.stringify({ pinned }) }
    ),

  test: (routerModelId: string) =>
    request<{
      ok: boolean
      router_model_id: string
      setup_status: LocalSetupStatus
      latency_ms: number | null
      error: string | null
    }>(`/local/models/${encodeURI(routerModelId)}/test`, { method: 'POST' }),

  remove: (routerModelId: string) =>
    request<{ ok: boolean }>(
      `/local/models/${encodeURI(routerModelId)}`,
      { method: 'DELETE' }
    ),

  startPull: (model: string, nodeId?: string) =>
    request<LocalPullProgress>('/local/models/pull', {
      method: 'POST',
      body: JSON.stringify({ model, node_id: nodeId }),
    }),

  pullStatus: (externalId: string, nodeId?: string) => {
    const qs = nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : ''
    return request<LocalPullProgress>(
      `/local/models/pull/${encodeURI(externalId)}${qs}`
    )
  },

  activePulls: () =>
    request<LocalActivePullsResponse>('/local/models/pulls/active'),

  cloudManifest: (nodeId?: string) => {
    const qs = nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : ''
    return request<LocalCloudManifest>(`/local/cloud/manifest${qs}`)
  },
}
