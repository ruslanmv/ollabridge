/**
 * Usage API client — typed wrappers around /v1/bi/* (usage/routes.py).
 *
 * OllaBridge Cloud serves the same response shapes, so these types describe
 * both. Money is integer micro-USD (1 USD = 1_000_000).
 */

import { ApiError } from './api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      detail = data?.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : ''
    } catch {
      // ignore
    }
    throw new ApiError(init?.method || 'GET', path, res.status, detail)
  }
  return res.json()
}

/** Share of tokens per data-quality badge; keys are absent when zero. */
export type MeasurementMix = Partial<Record<'verified' | 'observed' | 'estimated' | 'unavailable', number>>

export interface Kpi {
  value: number
  previous: number
  delta_pct: number | null
}

export interface UsageOverview {
  period: { from: string; to: string }
  total_tokens: Kpi & { measurement_mix: MeasurementMix }
  estimated_cost_micro: Kpi & { unpriced_tokens: number }
  billed_cost_micro: Kpi
  subscription_equivalent_micro: { value: number }
  active_agents: Kpi & { delta: number }
  requests: { value: number; failed: number; unknown_usage: number }
  budget: {
    limit_micro: number
    spent_micro: number
    remaining_micro: number
    remaining_pct: number
    projected_overrun: boolean
  } | null
  forecast: {
    month: string
    month_to_date_micro: number
    daily_average_micro: number
    projected_month_end_micro: number
  } | null
}

export interface UsageSeries {
  key: string
  values: number[]
  total: number
}

export interface UsageTimeseries {
  metric: 'tokens' | 'cost' | 'events'
  group_by: string
  days: string[]
  series: UsageSeries[]
}

export interface UsageBreakdown {
  by: string
  metric: string
  total: number
  items: { key: string; value: number; share: number }[]
}

export interface UsageAgent {
  application_id: string
  agent_id: string
  top_provider: string
  tokens: number
  cost_micro: number
  events: number
  failed: number
  delta_pct: number | null
  measurement_mix: MeasurementMix
}

export interface UsageInsight {
  id: string
  severity: 'info' | 'warning'
  title: string
  detail: string
  estimated_saving_micro: number | null
}

export interface UsageSources {
  capture_enabled: boolean
  sources: { source: string; events: number; last_seen: string }[]
  cloud_sync: { enabled: boolean; reason: string; counts: Record<string, number> }
  pricing_version: string
}

/** Currency costs are shown in. API amounts stay micro-USD; `usd_rate` is
 * units of `code` per 1 USD, set by the user (never fetched). */
export interface DisplayCurrency {
  code: string
  usd_rate: number
  source: 'default' | 'environment' | 'saved'
}

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10)
}

/** Query string for the last `days` days, ending today (UTC, like the API). */
function range(days: number): string {
  const to = new Date()
  const from = new Date(to.getTime() - (days - 1) * 86_400_000)
  return `from=${isoDay(from)}&to=${isoDay(to)}`
}

// ── Per-model view (/v1/bi/models, usage/model_usage.py) ──────────────────
// `null` means unknown, never zero.

export type CostStateName = 'priced' | 'partial' | 'unpriced' | 'subscription' | 'not_billed' | 'none'

export interface CostState {
  state: CostStateName
  /** micro-USD; a floor when `partial`, an API equivalent when `subscription`. */
  micro: number | null
  unpriced_tokens: number
  modes: string[]
}

export interface TokenSplit {
  total: number | null
  input: number | null
  output: number | null
}

export interface DailySeries {
  tokens: number[]
  requests: number[]
  cost: number[]
}

export interface ModelUsage {
  provider: string
  model: string
  source: string | null
  source_display_name: string | null
  runtime_unreachable: boolean
  /** false = not offered now; null = could not be checked. */
  in_inventory: boolean | null
  tokens: TokenSplit & { dimensions: Record<string, number | null> }
  requests: number
  failed: number
  unknown_usage: number
  errors: Record<string, number>
  requested_as: Record<string, number>
  measurement: Record<string, number>
  execution: string[]
  billing_providers: string[]
  cost: CostState
  avg_latency_ms: number | null
  last_seen: string | null
  daily: DailySeries
}

export interface ModelInsight {
  id: string
  kind: 'repeated_failures' | 'not_in_inventory' | 'spike' | 'unpriced_usage'
  severity: 'info' | 'warning'
  provider: string | null
  model: string | null
  evidence: Record<string, unknown>
}

export interface InventoryView {
  available: number | null
  used: number
  used_in_inventory?: number
  never_used: number | null
  not_in_inventory: number | null
  unreachable: { source: string; name: string; reason: string; provider_id?: string }[]
  by_source: Record<string, number>
  never_used_models: { provider: string; model: string; source_display_name: string | null; category: string | null }[]
}

export interface ModelUsageView {
  period: { from: string; to: string }
  capture_enabled: boolean
  days: string[]
  totals: {
    tokens: TokenSplit
    requests: number
    failed: number
    failed_pct: number | null
    unknown_usage: number
    models_used: number
    cost: CostState
  }
  daily: DailySeries
  models: ModelUsage[]
  sources: { attributed: boolean; items: { key: string; attributed: boolean; tokens: number; events: number; failed: number }[] }
  inventory: InventoryView
  insights: ModelInsight[]
}

export const usageApi = {
  models: (days: number) => request<ModelUsageView>(`/v1/bi/models?${range(days)}`),
  overview: (days: number) => request<UsageOverview>(`/v1/bi/overview?${range(days)}`),
  timeseries: (days: number, metric: 'tokens' | 'cost') =>
    request<UsageTimeseries>(`/v1/bi/timeseries?${range(days)}&metric=${metric}&group_by=provider`),
  breakdown: (days: number, metric: 'tokens' | 'cost') =>
    request<UsageBreakdown>(`/v1/bi/breakdown?${range(days)}&by=provider&metric=${metric}`),
  agents: (days: number) => request<{ total: number; items: UsageAgent[] }>(`/v1/bi/agents?${range(days)}&limit=8`),
  insights: (days: number) => request<{ items: UsageInsight[] }>(`/v1/bi/insights?${range(days)}`),
  sources: () => request<UsageSources>('/v1/bi/sources'),
  currency: () => request<DisplayCurrency>('/v1/bi/currency'),
  setCurrency: (code: string, usdRate: number | null) =>
    request<DisplayCurrency>('/v1/bi/currency', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, usd_rate: usdRate }),
    }),
  setBudget: (limitMicro: number | null) =>
    request<{ limit_micro: number | null }>('/v1/bi/budget', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit_micro: limitMicro }),
    }),
}
