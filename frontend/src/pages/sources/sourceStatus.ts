import type { ModelAccessListResponse, ModelAccessRecord, SourceObject } from '../../lib/api'

/**
 * The predicates behind every "N of M connected" and "Shared with Cloud"
 * reading in the UI.
 *
 * Both the Sources tab header (SourcesHubPage) and the External Runtimes card
 * on the Runtimes page (ExternalRuntimes) compute from these, so they cannot
 * drift apart again: they once showed "1 of 15" and "2 of 15" connected for
 * the same two sources, because one read `status` and the other merely
 * counted configured records.
 *
 * The definitions are also recorded in docs/UX_EXTERNAL_SOURCES.md under
 * "Status definitions"; keep the two in step.
 */

/**
 * Connected as the backend reports it. `_source_view` in
 * src/ollabridge/api/sources_routes.py says `connected` only when a key is
 * stored, the last test did not fail, no required extra field is missing AND
 * the source is enabled — a disabled source reports `disabled` whatever its
 * key says. Reading `status` rather than re-deriving it here keeps the UI
 * from inventing a second definition.
 */
export function isConnected(source: SourceObject): boolean {
  return source.status === 'connected'
}

/** A model is actually selected to serve (whitespace-only counts as none). */
export function hasDefaultModel(source: SourceObject): boolean {
  return source.default_model.trim().length > 0
}

/** The Models & Access record for one model of one source, if loaded. */
export function findModelAccess(
  access: ModelAccessListResponse | undefined,
  sourceId: string,
  modelId: string,
): ModelAccessRecord | undefined {
  const group = access?.sources.find((g) => g.source_id === sourceId)
  return group?.models.find((m) => m.model_id === modelId)
}

/**
 * Would the cloud manifest publish this source's selected model?
 *
 * Mirrors the backend: `_external_source_models` (model_access_routes.py)
 * drops disabled sources from the inventory, and `cloud_manifest`
 * (model_access.py) keeps a model only when its access record has
 * `enabled && visible_cloud`. So:
 *
 * - the source must be enabled, connected and have a default model;
 *   otherwise false, whatever `allow_routing` says;
 * - with `/admin/model-access` loaded, the per-model record decides;
 * - before it has loaded, or for a model no one has decided about yet, fall
 *   back to the source-level default the backend itself would assign
 *   (`_default_access`: cloud-visible iff the source has routing switched on).
 */
export function isSharedWithCloud(
  source: SourceObject,
  access?: ModelAccessListResponse,
): boolean {
  if (!source.enabled || !isConnected(source) || !hasDefaultModel(source)) return false
  const record = findModelAccess(access, source.name, source.default_model.trim())
  if (record) return record.enabled && record.visible_cloud
  return source.allow_routing
}

/**
 * Split a probe result such as "key rejected (HTTP 401): <provider's words>"
 * (provider_ops.test_provider) into the short verdict and the provider's
 * reason, so a form can lead with the verdict and keep the long reason one
 * click away.
 */
export function splitProbeDetail(detail: string): { summary: string; reason: string | null } {
  const m = /^(.*?\(HTTP \d{3}\)): ([\s\S]+)$/.exec(detail)
  return m ? { summary: m[1], reason: m[2] } : { summary: detail, reason: null }
}
