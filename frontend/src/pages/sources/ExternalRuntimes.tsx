import { motion } from 'framer-motion'
import { Cloud, CloudOff, Globe, Lock, Route, Share2 } from 'lucide-react'
import type { SourceObject } from '../../lib/api'
import { useSources } from '../../lib/hooks'
import type { Page } from '../../App'

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
 * Read-only by design: a source is configured in Sources, and duplicating
 * those controls here would give two places to change the same thing.
 */
export function ExternalRuntimes({ onNavigate }: { onNavigate?: (page: Page) => void }) {
  const { data, isLoading } = useSources()
  const configured = data?.configured ?? []
  const catalogSize = configured.length + (data?.available?.length ?? 0)
  const withModel = configured.filter((s) => s.default_model)
  const routing = configured.filter((s) => s.allow_routing && s.default_model)

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
              Switch routing on for a source and its model is shared with Cloud.
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
            {configured.length} of {catalogSize} connected · {withModel.length} default
            model{withModel.length === 1 ? '' : 's'} · {routing.length} routing to Cloud
          </p>
          <div className="space-y-2">
            {configured.map((source) => (
              <ExternalRuntimeRow key={source.name} source={source} />
            ))}
          </div>
        </>
      )}
    </motion.div>
  )
}

function ExternalRuntimeRow({ source }: { source: SourceObject }) {
  // Shared with Cloud only when routing is on AND a model is actually
  // selected — a source with neither is connected but not in service, and
  // saying "shared" for it would be a lie the user acts on.
  const inService = source.allow_routing && !!source.default_model
  const connected = source.status === 'connected'

  return (
    <div className="flex items-center gap-3 px-3.5 py-3 rounded-xl bg-navy-900/40 border border-white/[0.06]">
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{
          background: connected ? '#14b8a6' : '#f59e0b',
          boxShadow: `0 0 8px ${connected ? '#14b8a6' : '#f59e0b'}`,
        }}
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
        <Badge
          icon={source.storage_mode === 'local_only' ? Lock : Share2}
          label={source.storage_mode === 'local_only' ? 'Key local' : 'Key in vault'}
          tone="neutral"
        />
        <Badge
          icon={Route}
          label={source.allow_routing ? 'Routing on' : 'Routing off'}
          tone={source.allow_routing ? 'good' : 'neutral'}
        />
        <Badge
          icon={inService ? Cloud : CloudOff}
          label={inService ? 'Shared with Cloud' : 'Not shared'}
          tone={inService ? 'good' : 'neutral'}
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
