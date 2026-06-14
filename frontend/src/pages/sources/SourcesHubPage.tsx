import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Boxes,
  Layers,
  Route,
  Activity,
  Cloud,
  Plus,
  Loader2,
  AlertTriangle,
  Lock,
  ShieldCheck,
  Info,
} from 'lucide-react'
import type { AvailableSource, SourceObject } from '../../lib/api'
import { useSources } from '../../lib/hooks'
import { GlassCard } from './ui'
import { ConfiguredSourceCard, AvailableSourceCard } from './SourceCard'
import { SourceModal, type ModalTarget } from './SourceModal'
import { RotateModal } from './RotateModal'
import { ModelsAccessTab } from './ModelsAccessTab'

type Tab = 'sources' | 'models' | 'routing' | 'usage' | 'cloud'

const TABS: { id: Tab; label: string; icon: typeof Boxes }[] = [
  { id: 'sources', label: 'Sources', icon: Boxes },
  { id: 'models', label: 'Models & Access', icon: Layers },
  { id: 'routing', label: 'Routing', icon: Route },
  { id: 'usage', label: 'Usage', icon: Activity },
  { id: 'cloud', label: 'Cloud Sync', icon: Cloud },
]

// ── Skeleton ──────────────────────────────────────────────────────

function CardSkeleton() {
  return (
    <div className="rounded-2xl border border-white/5 bg-navy-800/40 p-5 animate-pulse">
      <div className="flex items-start justify-between mb-4">
        <div className="space-y-2">
          <div className="h-4 w-32 rounded bg-white/8" />
          <div className="h-3 w-20 rounded bg-white/5" />
        </div>
        <div className="h-6 w-24 rounded-full bg-white/5" />
      </div>
      <div className="h-3 w-28 rounded bg-white/5 mb-3" />
      <div className="flex gap-1.5 mb-4">
        <div className="h-5 w-16 rounded bg-white/5" />
        <div className="h-5 w-14 rounded bg-white/5" />
        <div className="h-5 w-16 rounded bg-white/5" />
      </div>
      <div className="flex gap-1.5">
        <div className="h-7 w-20 rounded-lg bg-white/5" />
        <div className="h-7 w-16 rounded-lg bg-white/5" />
        <div className="h-7 w-16 rounded-lg bg-white/5" />
      </div>
    </div>
  )
}

// ── Sources tab ───────────────────────────────────────────────────

function SourcesTab({
  onConfigure,
  onAdd,
  onRotate,
}: {
  onConfigure: (s: SourceObject) => void
  onAdd: (s: AvailableSource) => void
  onRotate: (s: SourceObject) => void
}) {
  const { data, isLoading, isError, error } = useSources()

  const configured = data?.configured ?? []
  const available = data?.available ?? []
  const total = configured.length + available.length
  const connected = configured.filter((s) => s.status === 'connected').length
  const models = configured.filter((s) => s.default_model.trim()).length

  return (
    <div className="space-y-8">
      {/* Status line + add button */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-white/55">
          {isLoading ? (
            <span className="inline-flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" /> Loading sources…
            </span>
          ) : (
            <span>
              <span className="text-white font-semibold">{connected}</span> of {total} connected
              <span className="text-white/25"> · </span>
              <span className="text-white font-semibold">{models}</span> default model
              {models === 1 ? '' : 's'}
            </span>
          )}
        </div>
        <button
          onClick={() => {
            // Prefer adding the first available; otherwise nudge nothing.
            if (available[0]) onAdd(available[0])
          }}
          disabled={available.length === 0}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-glow-cyan/20 border border-glow-cyan/40 text-glow-cyan hover:bg-glow-cyan/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus size={15} /> Add Source
        </button>
      </div>

      {isError && (
        <div className="flex items-start gap-2 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          <AlertTriangle size={16} className="shrink-0 mt-0.5" />
          <span>{(error as Error).message}</span>
        </div>
      )}

      {/* Configured */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : configured.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {configured.map((s, i) => (
            <ConfiguredSourceCard
              key={s.name}
              source={s}
              delay={i * 0.04}
              onConfigure={onConfigure}
              onRotate={onRotate}
            />
          ))}
        </div>
      ) : (
        !isError && (
          <div className="rounded-2xl border border-white/8 bg-navy-800/30 px-6 py-10 text-center">
            <div className="w-12 h-12 mx-auto mb-3 rounded-2xl flex items-center justify-center bg-glow-cyan/10 border border-glow-cyan/25">
              <Boxes size={22} className="text-glow-cyan" />
            </div>
            <h3 className="text-white/85 font-semibold">No sources yet</h3>
            <p className="text-white/40 text-sm mt-1 max-w-md mx-auto">
              Add your first AI account or endpoint below. New sources are local-only, private, and
              kept out of routing until you say otherwise.
            </p>
          </div>
        )
      )}

      {/* Add a source */}
      {!isLoading && available.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-white/80 font-semibold text-sm">Add a source</h2>
            <span className="text-white/30 text-xs">{available.length} available</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {available.map((s, i) => (
              <AvailableSourceCard key={s.name} source={s} delay={i * 0.03} onAdd={onAdd} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Placeholder tabs (honest empty states) ────────────────────────

function PlaceholderTab({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Route
  title: string
  children: React.ReactNode
}) {
  return (
    <GlassCard>
      <div className="flex flex-col items-center text-center py-10 px-6">
        <div className="w-14 h-14 mb-4 rounded-2xl flex items-center justify-center bg-white/5 border border-white/10">
          <Icon size={24} className="text-white/50" />
        </div>
        <h2 className="text-white font-semibold text-lg mb-2">{title}</h2>
        <div className="text-white/45 text-sm max-w-md leading-relaxed space-y-2">{children}</div>
      </div>
    </GlassCard>
  )
}

function RoutingTab() {
  const { data } = useSources()
  const configured = data?.configured ?? []
  const routable = configured.filter((s) => s.allow_routing && s.enabled)
  return (
    <PlaceholderTab icon={Route} title="Routing is disabled">
      <p>
        When disabled, every request uses exactly the source and model the caller selected.
        When enabled, OllaBridge may choose among sources you marked{' '}
        <span className="text-white/70">Allow routing</span>, following the active profile.
      </p>
      {configured.length === 0 ? (
        <p className="text-white/35">Add at least one source before enabling routing.</p>
      ) : (
        <p className="text-white/35">
          {routable.length === 0
            ? 'No sources are marked routable yet — enable "Allow routing" on a source first.'
            : `${routable.length} source${routable.length === 1 ? '' : 's'} ready for routing. Routing profiles are coming soon.`}
        </p>
      )}
    </PlaceholderTab>
  )
}

function UsageTab() {
  return (
    <PlaceholderTab icon={Activity} title="No usage yet">
      <p>Send a request through a configured source to see usage.</p>
      <p className="text-white/35">
        Real requests, latency, failures, and cost per source will appear here — nothing is
        fabricated.
      </p>
    </PlaceholderTab>
  )
}

function CloudSyncTab() {
  return (
    <div className="space-y-4">
      <PlaceholderTab icon={Cloud} title="Cloud Sync">
        <p>Two clearly separated levels. Both are opt-in and off by default.</p>
      </PlaceholderTab>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GlassCard>
          <div className="flex items-center gap-2.5 mb-2">
            <Info size={16} className="text-glow-cyan" />
            <h3 className="text-white/85 font-semibold text-sm">Metadata sync</h3>
          </div>
          <p className="text-white/45 text-[13px] leading-relaxed">
            Syncs source names, enabled state, default models, and routing profiles across your
            devices. <span className="text-white/70">Never keys.</span>
          </p>
        </GlassCard>
        <GlassCard>
          <div className="flex items-center gap-2.5 mb-2">
            <Lock size={16} className="text-glow-violet" />
            <h3 className="text-white/85 font-semibold text-sm">Encrypted vault sync</h3>
          </div>
          <p className="text-white/45 text-[13px] leading-relaxed">
            Optionally syncs your keys inside an end-to-end encrypted vault. Explicit opt-in,
            off by default — set a source's storage mode to{' '}
            <span className="text-white/70">Encrypted vault</span> to enroll it.
          </p>
        </GlassCard>
      </div>
    </div>
  )
}

// ── Root ──────────────────────────────────────────────────────────

export function SourcesHubPage() {
  const [tab, setTab] = useState<Tab>('sources')
  const [modal, setModal] = useState<ModalTarget | null>(null)
  const [rotateTarget, setRotateTarget] = useState<SourceObject | null>(null)

  return (
    <div className="relative h-full overflow-y-auto">
      <div className="absolute -top-32 -right-32 w-[500px] h-[500px] bloom-violet pointer-events-none" />
      <div className="absolute top-1/3 -left-32 w-[400px] h-[400px] bloom-cyan pointer-events-none" />

      <div className="relative max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <div
                className="w-11 h-11 rounded-2xl flex items-center justify-center glow-cyan"
                style={{
                  background:
                    'linear-gradient(135deg, rgba(0,229,255,0.2), rgba(139,92,246,0.1))',
                  border: '1px solid rgba(0,229,255,0.3)',
                }}
              >
                <Boxes size={20} className="text-glow-cyan" />
              </div>
              <h1 className="text-2xl font-bold text-white">External Sources</h1>
            </div>
            <p className="text-white/50 text-sm max-w-2xl leading-relaxed">
              Add your own AI accounts and endpoints, store keys locally, test them, and decide
              explicitly what may be shared or used for routing. Safe by default: new sources are
              local-only, private, and routing-off.
            </p>
          </div>
          <div className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 border border-white/8 text-[11px] text-white/45 shrink-0">
            <ShieldCheck size={13} className="text-glow-teal" /> Keys stay encrypted &amp; local
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-navy-800/40 border border-white/5 w-fit">
          {TABS.map((t) => {
            const Icon = t.icon
            const active = tab === t.id
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`relative inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  active ? 'text-white' : 'text-white/45 hover:text-white/75'
                }`}
              >
                {active && (
                  <motion.div
                    layoutId="sources-tab"
                    className="absolute inset-0 rounded-lg bg-glow-cyan/10 border border-glow-cyan/25"
                    transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                  />
                )}
                <Icon size={14} className="relative z-10" />
                <span className="relative z-10">{t.label}</span>
              </button>
            )
          })}
        </div>

        {/* Body */}
        <div>
          {tab === 'sources' && (
            <SourcesTab
              onConfigure={(s) => setModal({ mode: 'edit', source: s })}
              onAdd={(s) => setModal({ mode: 'add', source: s })}
              onRotate={(s) => setRotateTarget(s)}
            />
          )}
          {tab === 'models' && <ModelsAccessTab />}
          {tab === 'routing' && <RoutingTab />}
          {tab === 'usage' && <UsageTab />}
          {tab === 'cloud' && <CloudSyncTab />}
        </div>
      </div>

      {modal && <SourceModal target={modal} onClose={() => setModal(null)} />}
      {rotateTarget && (
        <RotateModal source={rotateTarget} onClose={() => setRotateTarget(null)} />
      )}
    </div>
  )
}
