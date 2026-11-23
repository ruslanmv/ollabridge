/**
 * Pure helpers for Models → Testing (no React; tested by `npm run test:unit`).
 * One check per model, two at a time; presets are opt-in.
 */

import type { Model } from '../../lib/api'
import type { ModelCheck } from '../../lib/modelChecksApi'

export const CONCURRENCY = 2
const PRESET = 'preset_or_workflow'

/** Models worth checking: chat models and models with no category (Ollama,
 * nodes). Presets and personas run on a base model, so they are opt-in. */
export function checkable(models: Model[], includePresets: boolean): Model[] {
  return models.filter((m) => includePresets || m.category !== PRESET)
}

export function presetCount(models: Model[]): number {
  return models.filter((m) => m.category === PRESET).length
}

export function sourceOf(m: Model): string {
  return m.source_display_name || m.source || m.owned_by || 'Unknown'
}

export function searchModels(models: Model[], query: string, source: string): Model[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return models.filter((m) => {
    if (source && sourceOf(m) !== source) return false
    const hay = `${m.id} ${sourceOf(m)}`.toLowerCase()
    return terms.every((t) => hay.includes(t))
  })
}

/** Select-all toggles only the rows that are visible. */
export function toggleAll(selected: Set<string>, visible: string[]): Set<string> {
  const next = new Set(selected)
  const allOn = visible.length > 0 && visible.every((id) => next.has(id))
  for (const id of visible) {
    if (allOn) next.delete(id)
    else next.add(id)
  }
  return next
}

export interface Summary {
  working: number
  slow: number
  notWorking: number
  checked: number
  /** Set when most failures share one cause that is about the provider or network. */
  sharedCause: string | null
}

const SHARED_CAUSES: Record<string, string> = {
  check_timeout: 'timed out',
  provider_timeout: 'timed out',
  rate_limited: 'were limited',
  network_offline: "couldn't be reached",
  connection_lost: "couldn't be reached",
  ollama_unreachable: "couldn't be reached",
  provider_unavailable: 'were unavailable',
}

export function summarize(results: ModelCheck[]): Summary {
  const working = results.filter((r) => r.verdict === 'working').length
  const slow = results.filter((r) => r.verdict === 'slow').length
  const failed = results.filter((r) => r.verdict === 'not_working')
  let sharedCause: string | null = null
  if (results.length >= 2 && failed.length / results.length > 0.5) {
    const byCause: Record<string, number> = {}
    for (const r of failed) {
      const cause = SHARED_CAUSES[r.reason_code]
      if (cause) byCause[cause] = (byCause[cause] ?? 0) + 1
    }
    const top = Object.entries(byCause).sort((a, b) => b[1] - a[1])[0]
    if (top && top[1] / results.length > 0.5) {
      sharedCause = `Most models ${top[0]} at the same time, so it's probably the provider or your network, not the models.`
    }
  }
  return { working, slow, notWorking: failed.length, checked: results.length, sharedCause }
}

/** Run `worker` over `ids`, at most `concurrency` at once, in order. Stops
 * starting new work once `signal` aborts; work already running finishes. */
export async function runQueue(
  ids: string[],
  worker: (id: string) => Promise<void>,
  concurrency = CONCURRENCY,
  signal?: { aborted: boolean },
): Promise<void> {
  let next = 0
  const lane = async () => {
    while (next < ids.length && !signal?.aborted) {
      const id = ids[next++]
      await worker(id)
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, ids.length) }, lane))
}

export function seconds(ms: number | null): string {
  return ms === null ? '—' : `${(ms / 1000).toFixed(1)} s`
}
