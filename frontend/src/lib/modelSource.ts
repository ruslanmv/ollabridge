import type { Model } from './api'

/**
 * Provenance helpers for `/v1/models` entries.
 *
 * The gateway stamps every entry with `source` (see `ModelSource`). A build
 * that predates the field is handled by the old heuristics, which are kept
 * here in one place instead of being repeated per page: a HomePilot model is
 * recognised by its `persona:`/`personality:` prefix or owner, and a model
 * with no owner at all was only ever produced by the local Ollama path.
 * Anything else is an external runtime and must never be counted as Ollama.
 */

export const OLLAMA_SOURCE = 'ollama'
export const HOMEPILOT_SOURCE = 'homepilot'

type ModelLike = Pick<Model, 'id' | 'owned_by' | 'source' | 'source_display_name'>

const HOMEPILOT_OWNERS = new Set(['homepilot', 'homepilot-persona', 'homepilot-personality'])

export function isHomePilotId(id: string): boolean {
  return id.startsWith('persona:') || id.startsWith('personality:')
}

/** The source id of a model, falling back to pre-`source` heuristics. */
export function modelSource(m: ModelLike): string {
  if (m.source) return m.source
  if (isHomePilotId(m.id) || (m.owned_by && HOMEPILOT_OWNERS.has(m.owned_by))) {
    return HOMEPILOT_SOURCE
  }
  if (!m.owned_by || m.owned_by === OLLAMA_SOURCE) return OLLAMA_SOURCE
  return m.owned_by
}

export function isOllamaModel(m: ModelLike): boolean {
  return modelSource(m) === OLLAMA_SOURCE
}

export function isHomePilotModel(m: ModelLike): boolean {
  return modelSource(m) === HOMEPILOT_SOURCE
}

/** A label fit for a pill: the gateway's display name, else the owner, else the source id. */
export function modelSourceLabel(m: ModelLike): string {
  if (m.source_display_name) return m.source_display_name
  const source = modelSource(m)
  if (source === OLLAMA_SOURCE) return 'Ollama'
  if (source === HOMEPILOT_SOURCE) return 'HomePilot'
  if (source.startsWith('byok:')) return m.owned_by || source.slice('byok:'.length)
  return m.owned_by || source
}

/** Group models by their source label, keeping first-seen order. */
export function groupBySource<T extends ModelLike>(models: T[]): Array<{ label: string; models: T[] }> {
  const groups = new Map<string, T[]>()
  for (const m of models) {
    const label = modelSourceLabel(m)
    const bucket = groups.get(label)
    if (bucket) bucket.push(m)
    else groups.set(label, [m])
  }
  return Array.from(groups, ([label, items]) => ({ label, models: items }))
}
