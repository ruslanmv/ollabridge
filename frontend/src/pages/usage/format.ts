/** Number formatting and the provider → colour assignment for the Usage page. */

import type { DisplayCurrency } from '../../lib/usageApi'

export function formatTokens(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`
  return String(value)
}

export const USD: DisplayCurrency = { code: 'USD', usd_rate: 1, source: 'default' }

/** Micro-USD → a figure in the display currency, e.g. "1.185,43 €" or
 * "$1,185.43", in the reader's own number format. Sub-cent amounts keep four
 * decimals. The ledger is USD; conversion happens here, at display time. */
export function formatMoney(micro: number, currency: DisplayCurrency = USD): string {
  const amount = (micro / 1_000_000) * currency.usd_rate
  const digits = amount !== 0 && Math.abs(amount) < 0.01 ? 4 : 2
  try {
    return amount.toLocaleString(undefined, {
      style: 'currency',
      currency: currency.code,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })
  } catch {
    // A code this browser's Intl data does not know.
    return `${amount.toFixed(digits)} ${currency.code}`
  }
}

export function formatMetric(metric: 'tokens' | 'cost', value: number, currency: DisplayCurrency = USD): string {
  return metric === 'cost' ? formatMoney(value, currency) : formatTokens(value)
}

export function formatDay(isoDay: string): string {
  return new Date(`${isoDay}T00:00:00Z`).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

// Categorical slots, validated against the app's dark surface (CVD-safe in
// this order). A provider keeps its colour whatever else is on screen: colour
// follows the entity, never its rank.
const SLOTS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#0ca30c', '#9085e9']
const OTHER = '#6b7280'

const KNOWN: Record<string, number> = {
  openai: 0,
  anthropic: 1,
  gemini: 2,
  google: 2,
  xai: 3,
  grok: 3,
  openrouter: 4,
  ollama: 5,
  watsonx: 6,
}

/** Stable colours for a set of series keys. Known providers have fixed slots;
 * the rest take the remaining slots in name order, and overflow shares grey. */
export function assignColors(keys: string[]): Record<string, string> {
  const colors: Record<string, string> = {}
  const taken = new Set<number>()
  for (const key of keys) {
    const slot = KNOWN[key.toLowerCase()]
    if (slot !== undefined && !taken.has(slot)) {
      colors[key] = SLOTS[slot]
      taken.add(slot)
    }
  }
  const free = SLOTS.map((_, index) => index).filter((index) => !taken.has(index))
  const rest = keys.filter((key) => !(key in colors) && key !== 'others').sort()
  for (const key of rest) {
    const slot = free.shift()
    colors[key] = slot === undefined ? OTHER : SLOTS[slot]
  }
  if (keys.includes('others')) colors.others = OTHER
  return colors
}
