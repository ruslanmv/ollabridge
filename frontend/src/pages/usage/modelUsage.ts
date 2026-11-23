/**
 * Pure helpers for the per-model usage view (no React, so they can be tested
 * with `npm run test:unit`). Rules: docs/USAGE_BY_MODEL_DESIGN.md.
 *
 * Unknown is never shown as zero, and a model is always shown by the id the
 * gateway served it under.
 */

import type {
  CostState,
  DisplayCurrency,
  ModelInsight,
  ModelUsage,
  ModelUsageView,
  UsageTimeseries,
} from '../../lib/usageApi'
import { formatMoney, formatTokens } from './format'

// ── page state ────────────────────────────────────────────────────────────

export type PageState = 'loading' | 'error' | 'capture_off' | 'empty' | 'ready'

export function pageState(query: { isLoading: boolean; isError: boolean; data?: ModelUsageView }): PageState {
  if (query.data) {
    if (!query.data.capture_enabled && query.data.totals.requests === 0) return 'capture_off'
    return query.data.totals.requests === 0 ? 'empty' : 'ready'
  }
  if (query.isError) return 'error'
  return 'loading'
}

// ── numbers ───────────────────────────────────────────────────────────────

/** Tokens, or an em dash when nothing was counted. */
export function tokensLabel(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : formatTokens(value)
}

export function percent(part: number, whole: number): string {
  if (!whole) return '—'
  const value = (part / whole) * 100
  return `${value < 10 && value > 0 ? value.toFixed(1) : Math.round(value)}%`
}

/** How a cost may be shown: a figure only where a price exists. */
export function costLabel(cost: CostState, currency: DisplayCurrency): { text: string; hint: string; muted: boolean } {
  switch (cost.state) {
    case 'priced':
      return { text: formatMoney(cost.micro ?? 0, currency), hint: 'Estimated from the price catalog or the provider', muted: false }
    case 'partial':
      return {
        text: `≥ ${formatMoney(cost.micro ?? 0, currency)}`,
        hint: `${formatTokens(cost.unpriced_tokens)} tokens have no price, so this is a minimum`,
        muted: false,
      }
    case 'unpriced':
      return { text: 'Unpriced', hint: 'No price is set for this usage (USAGE_PRICING_FILE)', muted: true }
    case 'subscription':
      return {
        text: formatMoney(cost.micro ?? 0, currency),
        hint: 'Covered by a subscription; shown at API prices for comparison',
        muted: true,
      }
    case 'not_billed': {
      const only = cost.modes.length === 1 ? cost.modes[0] : null
      const text = only === 'local' ? 'Local' : only === 'free_tier' ? 'Free tier' : 'Not billed'
      return { text, hint: 'Not charged per token', muted: true }
    }
    default:
      return { text: '—', hint: 'Nothing measured', muted: true }
  }
}

/** Sort value for the cost column: figures first, then states. */
function costRank(cost: CostState): number {
  return cost.micro ?? -1
}

// ── identity ──────────────────────────────────────────────────────────────

export function modelKey(m: Pick<ModelUsage, 'provider' | 'model'>): string {
  return `${m.provider}\u0000${m.model}`
}

/** Chart/legend label: the served id, with the provider only when the same id
 * was used through more than one provider. */
export function displayLabels(models: Pick<ModelUsage, 'provider' | 'model'>[]): Record<string, string> {
  const count: Record<string, number> = {}
  for (const m of models) count[m.model] = (count[m.model] ?? 0) + 1
  const out: Record<string, string> = {}
  for (const m of models) out[modelKey(m)] = count[m.model] > 1 ? `${m.model} · ${m.provider}` : m.model
  return out
}

export function humanize(value: string): string {
  return value.replaceAll('_', ' ')
}

// ── table ─────────────────────────────────────────────────────────────────

export type SortKey = 'model' | 'provider' | 'total' | 'input' | 'output' | 'requests' | 'failed' | 'cost'

function sortValue(m: ModelUsage, key: SortKey): string | number | null {
  switch (key) {
    case 'model':
      return m.model.toLowerCase()
    case 'provider':
      return m.provider.toLowerCase()
    case 'total':
      return m.tokens.total
    case 'input':
      return m.tokens.input
    case 'output':
      return m.tokens.output
    case 'requests':
      return m.requests
    case 'failed':
      return m.failed
    case 'cost':
      return costRank(m.cost)
  }
}

/** Stable sort; unknown values always sink to the bottom. */
export function sortModels(models: ModelUsage[], key: SortKey, dir: 'asc' | 'desc'): ModelUsage[] {
  const sign = dir === 'asc' ? 1 : -1
  return models
    .map((m, index) => ({ m, index, v: sortValue(m, key) }))
    .sort((a, b) => {
      if (a.v === null && b.v === null) return a.index - b.index
      if (a.v === null) return 1
      if (b.v === null) return -1
      if (a.v < b.v) return -sign
      if (a.v > b.v) return sign
      return a.index - b.index
    })
    .map(({ m }) => m)
}

/** Case-insensitive match on the model id, provider and runtime name. */
export function filterModels(models: ModelUsage[], query: string): ModelUsage[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return models
  return models.filter((m) => {
    const hay = `${m.model} ${m.provider} ${m.source_display_name ?? ''}`.toLowerCase()
    return terms.every((term) => hay.includes(term))
  })
}

// ── chart ─────────────────────────────────────────────────────────────────

export type ChartMetric = 'tokens' | 'requests' | 'cost'

/** Daily series stacked by model: the `top` largest plus "others". Built from
 * the same rows as the totals, so the stacks add up to the KPI. */
export function chartSeries(view: ModelUsageView, metric: ChartMetric, top = 6): UsageTimeseries {
  const labels = displayLabels(view.models)
  const ranked = view.models
    .map((m) => ({ key: labels[modelKey(m)], values: m.daily[metric] }))
    .map((s) => ({ ...s, total: s.values.reduce((a, b) => a + b, 0) }))
    .filter((s) => s.total > 0)
    .sort((a, b) => b.total - a.total || a.key.localeCompare(b.key))
  const series = ranked.slice(0, top)
  const rest = ranked.slice(top)
  if (rest.length) {
    const values = view.days.map((_, i) => rest.reduce((sum, s) => sum + s.values[i], 0))
    series.push({ key: 'others', values, total: values.reduce((a, b) => a + b, 0) })
  }
  return { metric: metric === 'requests' ? 'events' : metric, group_by: 'model', days: view.days, series }
}

// ── insights ──────────────────────────────────────────────────────────────

export function insightText(insight: ModelInsight): { title: string; detail: string } {
  const e = insight.evidence as Record<string, number | string | boolean | null | string[]>
  switch (insight.kind) {
    case 'repeated_failures':
      return {
        title: `${insight.model} failed ${e.failed} of ${e.requests} requests`,
        detail: `${e.top_error ? `Mostly ${humanize(String(e.top_error))}` : 'No error category recorded'} · ${insight.provider}${
          e.in_inventory === false ? ' · no longer in the model list' : ''
        }`,
      }
    case 'not_in_inventory':
      return {
        title: `${insight.model} is no longer offered by ${insight.provider}`,
        detail: `${e.requests} requests in this period${Number(e.failed) ? `, ${e.failed} failed` : ''}. It may have been renamed or removed.`,
      }
    case 'spike':
      return {
        title: `Token use on ${e.day} was ${e.factor}× a usual day`,
        detail: `${formatTokens(Number(e.tokens))} tokens, against a median of ${formatTokens(Number(e.median))}.`,
      }
    case 'unpriced_usage':
      return {
        title: `${formatTokens(Number(e.unpriced_tokens))} API tokens have no price`,
        detail: 'Estimated cost leaves them out. Add prices in the file set by USAGE_PRICING_FILE.',
      }
  }
}
