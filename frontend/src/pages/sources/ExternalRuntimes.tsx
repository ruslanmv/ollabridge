import { motion } from 'framer-motion'
import { Cloud, CloudOff, Globe, Lock, Route, Share2 } from 'lucide-react'
import type { ModelAccessListResponse, SourceObject } from '../../lib/api'
import { useModelAccess, useModels, useSources } from '../../lib/hooks'
import { groupBySource, isHomePilotModel, isOllamaModel } from '../../lib/modelSource'
import type { Page } from '../../App'
import { ModelPill, StatusBadge } from './ui'
import { hasDefaultModel, isConnected, isSharedWithCloud } from './sourceStatus'

/** Pills shown per source before collapsing into "+N more". */
const MAX_PILLS_PER_SOURCE = 24

/**
 * The external accounts acting as execution backends, shown under the local
 * ones on the Runtimes page.
 *
 * A connected source with routing switched on is a runtime like any other:
 * the gateway can pick it, and its selected model is published to OllaBridge
 * Cloud so a paired device can choose it. That was previously invisible here
 * — Runtimes listed only Ollama and HomePilot — so there was nowhere to see
 * that a Groq or watsonx account was actually in service.
 *
 * Every count and chip here uses the same predicates as the Sources tab
 * (./sourceStatus.ts). "Connected" is the backend status, which already folds
 * in `enabled`; "Shared with Cloud" reads the per-model `visible_cloud` flag
 * from Models & Access — the flag the cloud manifest actually filters on —
 * rather than guessing from the source's routing switch alone.
 *
 * Read-only by design: a source is configured in Sources, and duplicating
 * those controls here would give two places to change the same thing.
 *
 * Below the accounts, every model `/v1/models` serves from somewhere other
 * than Ollama or HomePilot is listed under its source. These used to be
 * shown on the Ollama card as if Ollama served them.
 */
export function ExternalRuntimes({ onNavigate }: { onNavigate?: (page: Page) => void }) {
  const { data, isLoading } = useSources()
  // The Runtimes page already holds this query for its Ollama section; React
  // Query dedupes it, so this reads cached data rather than fetching twice.
  const { data: access } = useModelAccess()
  const { data: modelsData } = useModels()
  const configured = data?.configured ?? []
  const catalogSize = configured.length + (data?.available?.length ?? 0)
  const connected = configured.filter(isConnected)
  const withModel = configured.filter(hasDefaultModel)
  const shared = configured.filter((s) => isSharedWithCloud(s, access))
  const served = (modelsData?.data ?? []).filter((m) => !isOllamaModel(m) && !isHomePilotModel(m))
  const servedBySource = groupBySource(served)

  return (
    <motion.div
      className="glass-card p-6"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className="flex items-start justify-between gap-4 mb-5">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center"
            style={{
              background: 'linear-gradient(135deg, #8b5cf620, #8b5cf608)',
              border: '1px solid #8b5cf630',
            }}
          >
            <Globe size={18} style={{ color: '#8b5cf6' }} />
          </div>
          <div>
            <h2 className="text-white/90 font-semibold text-base">External Runtimes</h2>
            <p className="text-white/40 text-xs">
              Connected accounts serving models from someone else&rsquo;s hardware.
              Switch routing on for an enabled source and its selected model is shared
              with Cloud; fine-tune per model under Models &amp; Access.
            </p>
          </div>
        </div>
        {onNavigate && (
          <button
            type="button"
            onClick={() => onNavigate('sources')}
            className="shrink-0 px-3 py-2 rounded-xl text-xs text-white/70 bg-white/[0.04] border border-white/10 hover:bg-white/[0.06]"
          >
            Manage in Sources
          </button>
        )}
      </div>

      {isLoading ? (
        <p className="text-white/40 text-sm">Loading external sources…</p>
      ) : configured.length === 0 ? (
        <p className="text-white/40 text-sm">
          No external accounts connected.{' '}
          {onNavigate ? (
            <button
              type="button"
              onClick={() => onNavigate('sources')}
              className="text-glow-cyan hover:underline"
            >
              Add one in Sources
            </button>
          ) : (
            'Add one in Sources'
          )}{' '}
          to serve models from Groq, watsonx, OpenRouter and others.
        </p>
      ) : (
        <>
          <p className="text-xs text-white/45 mb-4">
            {connected.length} of {catalogSize} connected · {withModel.length} default
            model{withModel.length === 1 ? '' : 's'} · {shared.length} shared with Cloud
          </p>
          <div className="space-y-2">
            {configured.map((source) => (
              <ExternalRuntimeRow key={source.name} source={source} access={access} />
            ))}
          </div>
        </>
      )}

      {servedBySource.length > 0 && (
        <div className="mt-5 pt-4 border-t border-white/[0.06]">
          <p className="text-xs text-white/45 mb-3">
            {served.length} model{served.length === 1 ? '' : 's'} served through this gateway by
            external runtimes. Each pill names its source; none of these is an Ollama model.
          </p>
          <div className="space-y-3">
            {servedBySource.map((group) => (
              <div key={group.label}>
                <div className="text-[10px] uppercase tracking-wider text-white/30 mb-1.5">
                  {group.label} · {group.models.length}
                </div>
                <div className="flex flex-wrap gap-2">
                  {group.models.slice(0, MAX_PILLS_PER_SOURCE).map((m) => (
                    <ModelPill key={m.id} label={m.id} source={group.label} />
                  ))}
                  {group.models.length > MAX_PILLS_PER_SOURCE ? (
                    <span className="text-xs text-white/30 self-center">
                      +{group.models.length - MAX_PILLS_PER_SOURCE} more
                    </span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  )
}

function ExternalRuntimeRow({
  source,
  access,
}: {
  source: SourceObject
  access: ModelAccessListResponse | undefined
}) {
  const connected = isConnected(source)
  const disabled = source.status === 'disabled'
  // Shared with Cloud only when the manifest would actually publish the
  // selected model: the source must be enabled and connected, have a model,
  // and that model's own cloud flag must be on. A disabled source with
  // routing switched on is dropped from the manifest, so saying "shared" for
  // it would be a lie the user acts on.
  const shared = isSharedWithCloud(source, access)
  const dot = connected ? '#14b8a6' : disabled ? 'rgba(255,255,255,0.25)' : '#f59e0b'

  return (
    <div
      className={`flex items-center gap-3 px-3.5 py-3 rounded-xl bg-navy-900/40 border border-white/[0.06] ${
        disabled ? 'opacity-60' : ''
      }`}
    >
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: dot, boxShadow: disabled ? 'none' : `0 0 8px ${dot}` }}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm text-white/85 font-medium truncate">
            {source.display_name || source.label}
          </span>
          <span className="text-[10px] text-white/25 uppercase tracking-wider shrink-0">
            {source.name}
          </span>
        </div>
        <div className="text-xs font-mono text-white/45 truncate mt-0.5">
          {source.default_model || 'no model selected'}
        </div>
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {/* Same badge the Sources cards use, so "Disabled", "Missing key" and
            "Error" read identically on both pages. Hidden when connected: the
            teal dot already says so. */}
        {!connected && <StatusBadge status={source.status} />}
        <Badge
          icon={source.storage_mode === 'local_only' ? Lock : Share2}
          label={source.storage_mode === 'local_only' ? 'Key local' : 'Key in vault'}
          tone="neutral"
        />
        <Badge
          icon={Route}
          label={source.allow_routing ? 'Routing on' : 'Routing off'}
          tone={source.allow_routing && connected ? 'good' : 'neutral'}
        />
        <Badge
          icon={shared ? Cloud : CloudOff}
          label={shared ? 'Shared with Cloud' : 'Not shared'}
          tone={shared ? 'good' : 'neutral'}
        />
      </div>
    </div>
  )
}

const TONES = {
  good: { bg: 'rgba(20,184,166,0.1)', border: 'rgba(20,184,166,0.25)', fg: '#5eead4' },
  neutral: { bg: 'rgba(255,255,255,0.03)', border: 'rgba(255,255,255,0.08)', fg: 'rgba(255,255,255,0.45)' },
} as const

function Badge({
  icon: Icon,
  label,
  tone,
}: {
  icon: typeof Cloud
  label: string
  tone: keyof typeof TONES
}) {
  const t = TONES[tone]
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium whitespace-nowrap"
      style={{ background: t.bg, border: `1px solid ${t.border}`, color: t.fg }}
    >
      <Icon size={10} /> {label}
    </span>
  )
}
