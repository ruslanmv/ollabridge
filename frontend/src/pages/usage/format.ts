/** Number formatting and the provider → colour assignment for the Usage page. */

export function formatTokens(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`
  return String(value)
}

/** Micro-USD → "$1,185.43". Sub-cent amounts keep four decimals. */
export function formatUsd(micro: number): string {
  const usd = micro / 1_000_000
  const digits = usd !== 0 && Math.abs(usd) < 0.01 ? 4 : 2
  return usd.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatMetric(metric: 'tokens' | 'cost', value: number): string {
  return metric === 'cost' ? formatUsd(value) : formatTokens(value)
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
