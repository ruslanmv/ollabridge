/**
 * Models & Access — the per-model sharing grid.
 *
 * One row per model, one independent toggle per access surface:
 * This PC · LAN · Cloud · per-app allow-list · Routing. Each toggle is a
 * single POST /admin/model-access/{source}/{model}; nothing here touches a
 * key (see docs/UX_SOURCES_MODEL.md — Source ≠ Access ≠ Routing ≠ Keys).
 *
 * Safe defaults are visible in the UI itself: a fresh model is on for
 * "This PC" and off everywhere else until the user opts in.
 */
import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Loader2,
  AlertTriangle,
  Layers,
  Monitor,
  Network,
  Cloud,
  Route,
  AppWindow,
  Plus,
  X,
  ShieldCheck,
  HardDrive,
} from 'lucide-react'
import type { ModelAccessPatch, ModelAccessRecord } from '../../lib/api'
import {
  useCloudModelManifest,
  useModelAccess,
  useSetModelAccess,
} from '../../lib/hooks'
import { GlassCard } from './ui'

const SUGGESTED_APP = 'yourfriend.online'

// ── Toggle pill ───────────────────────────────────────────────────

function Toggle({
  on,
  busy = false,
  disabled = false,
  color = '#00e5ff',
  title,
  onClick,
}: {
  on: boolean
  busy?: boolean
  disabled?: boolean
  color?: string
  title?: string
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      title={title}
      disabled={disabled || busy}
      onClick={onClick}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
        disabled ? 'opacity-30 cursor-not-allowed' : 'cursor-pointer'
      }`}
      style={{
        background: on ? `${color}38` : 'rgba(255,255,255,0.08)',
        border: `1px solid ${on ? `${color}70` : 'rgba(255,255,255,0.12)'}`,
      }}
    >
      {busy ? (
        <Loader2 size={11} className="mx-auto animate-spin text-white/60" />
      ) : (
        <span
          className="inline-block h-3.5 w-3.5 rounded-full transition-transform"
          style={{
            transform: on ? 'translateX(18px)' : 'translateX(2px)',
            background: on ? color : 'rgba(255,255,255,0.45)',
            boxShadow: on ? `0 0 8px ${color}80` : 'none',
          }}
        />
      )}
    </button>
  )
}

// ── Apps allow-list cell ──────────────────────────────────────────

function AppsCell({
  rec,
  busy,
  onApps,
}: {
  rec: ModelAccessRecord
  busy: boolean
  onApps: (apps: string[]) => void
}) {
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const dimmed = !rec.visible_cloud

  const add = (app: string) => {
    const v = app.trim().toLowerCase()
    if (!v || rec.allowed_apps.includes(v)) return
    onApps([...rec.allowed_apps, v])
    setDraft('')
    setAdding(false)
  }

  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${dimmed ? 'opacity-40' : ''}`}>
      {rec.allowed_apps.map((app) => (
        <span
          key={app}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-glow-violet/12 border border-glow-violet/30 text-glow-violet"
        >
          <AppWindow size={10} />
          {app}
          <button
            type="button"
            title={`Remove ${app}`}
            disabled={busy}
            onClick={() => onApps(rec.allowed_apps.filter((a) => a !== app))}
            className="ml-0.5 text-glow-violet/60 hover:text-glow-violet"
          >
            <X size={10} />
          </button>
        </span>
      ))}
      {!rec.allowed_apps.includes(SUGGESTED_APP) && !adding && (
        <button
          type="button"
          disabled={busy || dimmed}
          title={
            dimmed
              ? 'Publish to Cloud first, then allow specific apps'
              : `Allow ${SUGGESTED_APP} to use this model`
          }
          onClick={() => add(SUGGESTED_APP)}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] text-white/40 border border-dashed border-white/15 hover:text-white/70 hover:border-white/30 transition-colors disabled:cursor-not-allowed"
        >
          <Plus size={10} /> {SUGGESTED_APP}
        </button>
      )}
      {adding ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') add(draft)
            if (e.key === 'Escape') {
              setDraft('')
              setAdding(false)
            }
          }}
          onBlur={() => {
            setDraft('')
            setAdding(false)
          }}
          placeholder="app domain…"
          className="w-32 px-2 py-0.5 rounded-md text-[11px] bg-navy-900/60 border border-white/15 text-white placeholder-white/25 outline-none focus:border-glow-cyan/50"
        />
      ) : (
        <button
          type="button"
          disabled={busy || dimmed}
          title={dimmed ? 'Publish to Cloud first' : 'Allow another app'}
          onClick={() => setAdding(true)}
          className="inline-flex items-center justify-center w-5 h-5 rounded-md text-white/35 border border-white/10 hover:text-white/70 hover:border-white/25 transition-colors disabled:cursor-not-allowed"
        >
          <Plus size={11} />
        </button>
      )}
    </div>
  )
}

// ── Model row ─────────────────────────────────────────────────────

const GRID = 'grid grid-cols-[minmax(180px,1.4fr)_70px_70px_70px_minmax(180px,1.6fr)_70px] gap-3 items-center'

function ModelRow({ rec, delay }: { rec: ModelAccessRecord; delay: number }) {
  const mutate = useSetModelAccess()
  // Track which flag is in flight so only that toggle shows a spinner.
  const [pendingFlag, setPendingFlag] = useState<string | null>(null)

  const patch = (flag: string, body: ModelAccessPatch) => {
    setPendingFlag(flag)
    mutate.mutate(
      { sourceId: rec.source_id, modelId: rec.model_id, body },
      { onSettled: () => setPendingFlag(null) },
    )
  }

  const busy = mutate.isPending

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay }}
      className={`${GRID} px-4 py-3 rounded-xl border border-white/5 bg-navy-900/30 hover:bg-navy-900/50 transition-colors`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <HardDrive size={14} className="text-glow-cyan/70 shrink-0" />
        <span className="font-mono text-[13px] text-white/85 truncate" title={rec.model_id}>
          {rec.model_id}
        </span>
        {rec.visible_cloud && (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wide bg-glow-cyan/12 border border-glow-cyan/30 text-glow-cyan shrink-0">
            Published
          </span>
        )}
      </div>
      <Toggle
        on={rec.visible_local}
        busy={pendingFlag === 'visible_local'}
        disabled={busy && pendingFlag !== 'visible_local'}
        title="Serve this model on this computer's local API"
        onClick={() => patch('visible_local', { visible_local: !rec.visible_local })}
      />
      <Toggle
        on={rec.visible_lan}
        busy={pendingFlag === 'visible_lan'}
        disabled // forward-looking: persisted but not yet enforced — keep it honest
        color="#14b8a6"
        title="Local-network visibility is coming soon (not yet enforced)"
      />
      <Toggle
        on={rec.visible_cloud}
        busy={pendingFlag === 'visible_cloud'}
        disabled={busy && pendingFlag !== 'visible_cloud'}
        color="#8b5cf6"
        title="Publish to OllaBridge Cloud — requests relay back to this device; no key leaves this PC"
        onClick={() => patch('visible_cloud', { visible_cloud: !rec.visible_cloud })}
      />
      <AppsCell
        rec={rec}
        busy={busy}
        onApps={(apps) => patch('allowed_apps', { allowed_apps: apps })}
      />
      <Toggle
        on={rec.allow_routing}
        busy={pendingFlag === 'allow_routing'}
        disabled={busy && pendingFlag !== 'allow_routing'}
        color="#f59e0b"
        title="Let the router auto-select this model (off by default)"
        onClick={() => patch('allow_routing', { allow_routing: !rec.allow_routing })}
      />
    </motion.div>
  )
}

// ── Tab root ──────────────────────────────────────────────────────

export function ModelsAccessTab() {
  const { data, isLoading, isError, error } = useModelAccess()
  const manifest = useCloudModelManifest()

  const sources = data?.sources ?? []
  const { totalModels, publishedCount } = useMemo(() => {
    const all = sources.flatMap((s) => s.models)
    return {
      totalModels: all.length,
      publishedCount: all.filter((m) => m.visible_cloud).length,
    }
  }, [sources])

  return (
    <div className="space-y-6">
      {/* Status line */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-white/55">
          {isLoading ? (
            <span className="inline-flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" /> Loading models…
            </span>
          ) : (
            <span>
              <span className="text-white font-semibold">{totalModels}</span> model
              {totalModels === 1 ? '' : 's'} across{' '}
              <span className="text-white font-semibold">{sources.length}</span> source
              {sources.length === 1 ? '' : 's'}
              <span className="text-white/25"> · </span>
              <span className="text-white font-semibold">{publishedCount}</span> published to cloud
            </span>
          )}
        </div>
        <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 border border-white/8 text-[11px] text-white/45">
          <ShieldCheck size={13} className="text-glow-teal" />
          New models default to this PC only — sharing is always opt-in
        </div>
      </div>

      {isError && (
        <div className="flex items-start gap-2 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          <AlertTriangle size={16} className="shrink-0 mt-0.5" />
          <span>{(error as Error).message}</span>
        </div>
      )}

      {/* Per-source groups */}
      {!isLoading && sources.length === 0 && !isError && (
        <div className="rounded-2xl border border-white/8 bg-navy-800/30 px-6 py-10 text-center">
          <div className="w-12 h-12 mx-auto mb-3 rounded-2xl flex items-center justify-center bg-glow-cyan/10 border border-glow-cyan/25">
            <Layers size={22} className="text-glow-cyan" />
          </div>
          <h3 className="text-white/85 font-semibold">No models discovered yet</h3>
          <p className="text-white/40 text-sm mt-1 max-w-md mx-auto">
            Make sure Ollama is running on this computer (or connect a source in the Sources
            tab), and your models will appear here with per-model sharing controls.
          </p>
        </div>
      )}

      {sources.map((src, si) => (
        <GlassCard key={src.source_id} delay={si * 0.05} className="!p-5">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center bg-glow-cyan/10 border border-glow-cyan/25">
              <Monitor size={15} className="text-glow-cyan" />
            </div>
            <div>
              <h2 className="text-white/90 font-semibold text-sm leading-tight">
                {src.source_label}
              </h2>
              <p className="text-white/35 text-[11px]">
                {src.models.length} model{src.models.length === 1 ? '' : 's'} · executes on this
                device
              </p>
            </div>
          </div>

          {/* Column headers */}
          <div className={`${GRID} px-4 pb-2 text-[10px] font-semibold uppercase tracking-wider text-white/35`}>
            <span>Model</span>
            <span className="inline-flex items-center gap-1">
              <Monitor size={10} /> This PC
            </span>
            <span className="inline-flex items-center gap-1" title="Coming soon">
              <Network size={10} /> LAN
              <span className="px-1 rounded bg-white/8 text-[8px] normal-case tracking-normal">
                soon
              </span>
            </span>
            <span className="inline-flex items-center gap-1">
              <Cloud size={10} /> Cloud
            </span>
            <span className="inline-flex items-center gap-1">
              <AppWindow size={10} /> Allowed apps
            </span>
            <span className="inline-flex items-center gap-1">
              <Route size={10} /> Routing
            </span>
          </div>

          <div className="space-y-1.5">
            {src.models.map((rec, mi) => (
              <ModelRow
                key={`${rec.source_id}/${rec.model_id}`}
                rec={rec}
                delay={si * 0.05 + mi * 0.03}
              />
            ))}
          </div>
        </GlassCard>
      ))}

      {/* Cloud manifest preview — exactly what the cloud sees */}
      {!isLoading && totalModels > 0 && (
        <GlassCard delay={0.15} className="!p-5">
          <div className="flex items-center gap-2.5 mb-2">
            <Cloud size={16} className="text-glow-violet" />
            <h3 className="text-white/85 font-semibold text-sm">
              Published to OllaBridge Cloud
            </h3>
            <span className="text-white/30 text-xs">
              {manifest.data?.count ?? 0} model{(manifest.data?.count ?? 0) === 1 ? '' : 's'}
            </span>
          </div>
          {manifest.data && manifest.data.count > 0 ? (
            <div className="flex flex-wrap gap-2 mt-3">
              {manifest.data.models.map((m) => (
                <span
                  key={`${m.source_id}/${m.model_id}`}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[12px] font-mono bg-glow-violet/10 border border-glow-violet/25 text-white/75"
                  title={`Source: ${m.source_label} · requires this device online${
                    m.allowed_apps.length
                      ? ` · apps: ${m.allowed_apps.join(', ')}`
                      : ' · all paired apps'
                  }`}
                >
                  {m.model_id}
                  {m.allowed_apps.length > 0 && (
                    <span className="text-glow-violet text-[10px] font-sans">
                      {m.allowed_apps.length} app{m.allowed_apps.length === 1 ? '' : 's'}
                    </span>
                  )}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-white/40 text-[13px] leading-relaxed">
              Nothing is published. Toggle <span className="text-white/70">Cloud</span> on a model
              above to make it available to your paired apps — requests relay back to this device,
              and your keys never leave this computer.
            </p>
          )}
        </GlassCard>
      )}
    </div>
  )
}
