/**
 * Design draft for the upgraded Local Model Fleet page.
 *
 * This file is intentionally **not wired into the router**. It captures the
 * structure described in `docs/LOCAL_MODELS_UX_DESIGN.md` as compilable
 * TSX so the team can iterate on the layout, copy, and prop shapes before
 * replacing the current `ModelsPage.tsx`.
 *
 * Hooks come from `../../lib/localHooks` and `../../lib/localApi` — the
 * stubs are already merged so this file compiles against the real
 * `/local/*` endpoints.
 */

import { useMemo, useState } from 'react'
import {
  Brain, RefreshCw, Plus, Download, Cloud, CheckCircle2, AlertTriangle,
  HardDrive, Cpu, ShieldCheck, Search, Pin, PinOff, HeartPulse, Trash2,
  ChevronDown, Sparkles, X, Filter, ArrowDownUp, EyeOff, Eye, Loader2,
} from 'lucide-react'
import {
  useActivePulls, useCloudManifest, useEnableLocalModel, useLocalModels,
  useLocalRuntimeInfo, useLocalTopModels, useManualAddLocalModel,
  usePinLocalModel, useStartLocalPull, useSyncLocalCatalog,
  useTestLocalModel, useDeleteLocalModel,
} from '../../lib/localHooks'
import type { LocalModel, LocalPullProgress } from '../../lib/localApi'

// ── Curated quick-add gallery (industry-best free models on Ollama) ────

const RECOMMENDED_TAGS: Array<{
  tag: string
  title: string
  family: string
  size_label: string
  approx_gb: string
  tags: string[]
}> = [
  { tag: 'qwen2.5:7b',       title: 'Qwen 2.5 7B',        family: 'qwen',    size_label: '7B',  approx_gb: '4.4 GB', tags: ['general', 'tools'] },
  { tag: 'qwen2.5:14b',      title: 'Qwen 2.5 14B',       family: 'qwen',    size_label: '14B', approx_gb: '8.9 GB', tags: ['general', 'tools'] },
  { tag: 'llama3.1:8b',      title: 'Llama 3.1 8B',       family: 'llama',   size_label: '8B',  approx_gb: '4.7 GB', tags: ['general', 'tools'] },
  { tag: 'llama3.2:3b',      title: 'Llama 3.2 3B',       family: 'llama',   size_label: '3B',  approx_gb: '2.0 GB', tags: ['fast',  'tiny'] },
  { tag: 'mistral:7b',       title: 'Mistral 7B Instruct',family: 'mistral', size_label: '7B',  approx_gb: '4.1 GB', tags: ['general'] },
  { tag: 'phi3.5:3.8b',      title: 'Phi 3.5 Mini',       family: 'phi',     size_label: '3.8B',approx_gb: '2.3 GB', tags: ['small', 'efficient'] },
  { tag: 'gemma2:9b',        title: 'Gemma 2 9B',         family: 'gemma',   size_label: '9B',  approx_gb: '5.4 GB', tags: ['general'] },
  { tag: 'nomic-embed-text', title: 'Nomic Embed Text',   family: 'nomic',   size_label: '—',   approx_gb: '274 MB', tags: ['embeddings'] },
]

// ── Page ──────────────────────────────────────────────────────────────

export function ModelsDesignPage() {
  const runtime = useLocalRuntimeInfo()
  const list = useLocalModels()
  const top = useLocalTopModels(undefined, 3)
  const pulls = useActivePulls()
  const manifest = useCloudManifest()

  const sync = useSyncLocalCatalog()
  const enable = useEnableLocalModel()
  const pin = usePinLocalModel()
  const test = useTestLocalModel()
  const remove = useDeleteLocalModel()
  const startPull = useStartLocalPull()
  const manualAdd = useManualAddLocalModel()

  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<
    'all' | 'enabled' | 'top' | 'tools' | 'vision' | 'embeddings'
    | 'pinned' | 'manual' | 'pulling' | 'broken' | 'removed'
  >('all')
  const [selectedFamilies, setSelectedFamilies] = useState<Set<string>>(new Set())
  const [sort, setSort] = useState<'score' | 'size_asc' | 'size_desc' | 'latency' | 'recent'>('score')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [openModal, setOpenModal] = useState<
    | null
    | { kind: 'manual' }
    | { kind: 'pull'; tag: string }
    | { kind: 'test'; routerId: string }
    | { kind: 'metadata'; routerId: string }
    | { kind: 'remove'; routerId: string }
  >(null)
  const [shareLocalDefault, setShareLocalDefault] = useState(true)

  const models = list.data?.models ?? []
  const stats = list.data?.stats ?? runtime.data?.stats
  const nodes = list.data?.nodes ?? (runtime.data ? [runtime.data.node_id] : [])
  const topModels = top.data?.models ?? []
  const activePulls = pulls.data?.pulls ?? []

  // ── Derived: filtered + sorted ──────────────────────────────────────
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const rows = models.filter((m) => {
      if (q && !`${m.external_model_id} ${m.family ?? ''} ${m.node_id}`.toLowerCase().includes(q)) return false
      if (filter === 'enabled' && !m.enabled) return false
      if (filter === 'top' && !m.is_top_recommended) return false
      if (filter === 'tools' && !(m.capabilities?.supports_tools)) return false
      if (filter === 'vision' && !(m.capabilities?.supports_vision)) return false
      if (filter === 'embeddings' && !(m.capabilities?.supports_embeddings)) return false
      if (filter === 'pinned' && !m.pinned) return false
      if (filter === 'manual' && !m.manually_added) return false
      if (filter === 'pulling' && m.setup_status !== 'pulling') return false
      if (filter === 'broken' && m.setup_status !== 'broken') return false
      if (filter === 'removed' && m.setup_status !== 'removed') return false
      if (selectedFamilies.size > 0 && !selectedFamilies.has((m.family ?? '').toLowerCase())) return false
      return true
    })
    const sorter: Record<typeof sort, (a: LocalModel, b: LocalModel) => number> = {
      score:      (a, b) => (b.score - a.score) || a.router_model_id.localeCompare(b.router_model_id),
      size_asc:   (a, b) => (a.parameter_count ?? 0) - (b.parameter_count ?? 0),
      size_desc:  (a, b) => (b.parameter_count ?? 0) - (a.parameter_count ?? 0),
      latency:    (a, b) => (a.latency_observed_ms ?? Infinity) - (b.latency_observed_ms ?? Infinity),
      recent:     (a, b) => +new Date(b.modified_at ?? 0) - +new Date(a.modified_at ?? 0),
    }
    return [...rows].sort(sorter[sort])
  }, [models, search, filter, selectedFamilies, sort])

  // ── Group by node so the table is sectioned ─────────────────────────
  const byNode = useMemo(() => {
    const map = new Map<string, LocalModel[]>()
    for (const m of visible) {
      const arr = map.get(m.node_id) ?? []
      arr.push(m)
      map.set(m.node_id, arr)
    }
    return Array.from(map.entries())
  }, [visible])

  // ── Render ──────────────────────────────────────────────────────────
  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      <CommandBar
        runtime={runtime.data}
        manifest={manifest.data}
        onSync={() => sync.mutate({})}
        onPull={() => setOpenModal({ kind: 'pull', tag: '' })}
        onManual={() => setOpenModal({ kind: 'manual' })}
        syncing={sync.isPending}
      />

      {runtime.data && !runtime.data.reachable && (
        <RuntimeDownBanner runtime={runtime.data} />
      )}

      <KpiTiles
        runtime={runtime.data}
        stats={stats}
        pullingCount={activePulls.length}
      />

      {activePulls.length > 0 && <ActivePullsBanner pulls={activePulls} />}

      {topModels.length > 0 && (
        <TopRecommendedShelf
          models={topModels}
          onToggle={(m) => enable.mutate({ routerModelId: m.router_model_id, enabled: !m.enabled })}
          onTest={(m) => test.mutate(m.router_model_id)}
          onPin={(m) => pin.mutate({ routerModelId: m.router_model_id, pinned: !m.pinned })}
        />
      )}

      <SideRail
        runtime={runtime.data}
        stats={stats}
        manifest={manifest.data}
        shareLocalDefault={shareLocalDefault}
        setShareLocalDefault={setShareLocalDefault}
      />

      <FilterBar
        search={search}
        setSearch={setSearch}
        filter={filter}
        setFilter={setFilter}
        selectedFamilies={selectedFamilies}
        setSelectedFamilies={setSelectedFamilies}
        sort={sort}
        setSort={setSort}
      />

      {selected.size > 0 && (
        <BulkActionsDrawer
          count={selected.size}
          onClear={() => setSelected(new Set())}
          onEnable={(on) => {
            selected.forEach((id) =>
              enable.mutate({ routerModelId: id, enabled: on }),
            )
            setSelected(new Set())
          }}
          onPin={(on) => {
            selected.forEach((id) =>
              pin.mutate({ routerModelId: id, pinned: on }),
            )
            setSelected(new Set())
          }}
          onTest={() => {
            selected.forEach((id) => test.mutate(id))
          }}
        />
      )}

      {/* Per-node tables */}
      {nodes.length === 0 && !runtime.isLoading && (
        <EmptyCatalogState
          runtime={runtime.data}
          onPullRecommended={() => RECOMMENDED_TAGS.slice(0, 3).forEach((r) =>
            startPull.mutate({ model: r.tag, nodeId: runtime.data?.node_id })
          )}
          onPullCustom={() => setOpenModal({ kind: 'pull', tag: '' })}
          onAddManual={() => setOpenModal({ kind: 'manual' })}
        />
      )}

      {byNode.map(([nodeId, rows]) => (
        <NodeTable
          key={nodeId}
          nodeId={nodeId}
          rows={rows}
          selected={selected}
          onSelect={(id, on) => {
            const next = new Set(selected)
            if (on) next.add(id); else next.delete(id)
            setSelected(next)
          }}
          onEnable={(m) => enable.mutate({ routerModelId: m.router_model_id, enabled: !m.enabled })}
          onPin={(m) => pin.mutate({ routerModelId: m.router_model_id, pinned: !m.pinned })}
          onTest={(m) => setOpenModal({ kind: 'test', routerId: m.router_model_id })}
          onMetadata={(m) => setOpenModal({ kind: 'metadata', routerId: m.router_model_id })}
          onRemove={(m) => setOpenModal({ kind: 'remove', routerId: m.router_model_id })}
        />
      ))}

      <PullGallery
        installed={new Set(models.map((m) => m.external_model_id))}
        active={new Set(activePulls.filter((p) => p.status === 'running').map((p) => p.external_model_id))}
        onPull={(tag) => startPull.mutate({ model: tag, nodeId: runtime.data?.node_id })}
        onPullCustom={() => setOpenModal({ kind: 'pull', tag: '' })}
      />

      {/* Modals */}
      {openModal?.kind === 'manual' && (
        <ManualAddModal
          nodes={nodes}
          onClose={() => setOpenModal(null)}
          onSubmit={(payload) => {
            manualAdd.mutate(payload, { onSuccess: () => setOpenModal(null) })
          }}
        />
      )}
      {openModal?.kind === 'pull' && (
        <PullProgressModal
          initialTag={openModal.tag}
          nodeId={runtime.data?.node_id}
          onClose={() => setOpenModal(null)}
          onStart={(tag) => startPull.mutate({ model: tag, nodeId: runtime.data?.node_id })}
        />
      )}
      {openModal?.kind === 'test' && (
        <TestResultModal routerId={openModal.routerId} onClose={() => setOpenModal(null)} />
      )}
      {openModal?.kind === 'metadata' && (
        <RawMetadataModal
          model={models.find((m) => m.router_model_id === openModal.routerId)}
          onClose={() => setOpenModal(null)}
        />
      )}
      {openModal?.kind === 'remove' && (
        <ConfirmRemoveModal
          routerId={openModal.routerId}
          onClose={() => setOpenModal(null)}
          onConfirm={() => {
            remove.mutate(openModal.routerId, { onSuccess: () => setOpenModal(null) })
          }}
        />
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 1 — Command bar
// ─────────────────────────────────────────────────────────────────────

function CommandBar({
  runtime, manifest, onSync, onPull, onManual, syncing,
}: {
  runtime: any
  manifest: any
  onSync: () => void
  onPull: () => void
  onManual: () => void
  syncing: boolean
}) {
  const reachable = runtime?.reachable
  const cloudConnected = !!manifest?.node?.id
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-glow-violet/30 to-glow-cyan/20 border border-white/10 grid place-items-center">
          <Brain size={20} className="text-glow-cyan" />
        </div>
        <div>
          <h1 className="text-xl font-bold">Local Model Fleet</h1>
          <p className="text-xs text-white/40 mt-0.5">
            Discover, pull, and share the models on this machine.
          </p>
          <p className="text-[11px] text-white/35 mt-1 font-mono">
            runtime: {runtime?.runtime ?? '—'} →{' '}
            <span className={reachable ? 'text-glow-teal' : 'text-glow-pink'}>
              {runtime?.runtime_base_url ?? '—'} ({reachable ? 'reachable' : 'down'})
            </span>
            {cloudConnected && (
              <>
                {' · '}
                <Cloud size={11} className="inline -mt-0.5" /> shared{' '}
                {(manifest.stats?.enabled ?? 0)}
              </>
            )}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 justify-end">
        <button className="btn-ghost" onClick={onManual}>
          <Plus size={14} /> Add manual
        </button>
        <button className="btn-ghost" onClick={onPull}>
          <Download size={14} /> Pull model
        </button>
        <button className="btn-primary" onClick={onSync} disabled={syncing}>
          {syncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          {syncing ? 'Syncing…' : 'Sync now'}
        </button>
      </div>
    </header>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 2 — KPIs
// ─────────────────────────────────────────────────────────────────────

function KpiTiles({ runtime, stats, pullingCount }: any) {
  const tiles = [
    { label: 'Installed', value: stats?.total ?? '—', hint: 'discovered on disk', color: 'text-white' },
    { label: 'Enabled', value: stats?.enabled ?? '—', hint: 'available to routing', color: 'text-glow-teal' },
    { label: 'Top recommended', value: stats?.top_recommended ?? '—', hint: 'auto-selected', color: 'text-glow-violet' },
    { label: 'Disk used', value: formatBytes(stats?.total_disk_bytes ?? 0), hint: pullingCount ? `${pullingCount} pulling…` : 'across this node', color: 'text-glow-cyan' },
  ]
  void runtime
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
          <div className="text-[10px] uppercase tracking-wider text-white/40">{t.label}</div>
          <div className={`text-2xl font-extrabold mt-1 tabular-nums ${t.color}`}>{t.value}</div>
          <div className="text-[11px] text-white/35 mt-1">{t.hint}</div>
        </div>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 3 — Active pulls banner
// ─────────────────────────────────────────────────────────────────────

function ActivePullsBanner({ pulls }: { pulls: LocalPullProgress[] }) {
  return (
    <div className="rounded-2xl border border-glow-cyan/25 bg-glow-cyan/5 p-3 space-y-2">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <Loader2 size={14} className="animate-spin text-glow-cyan" />
        Pulling {pulls.length} model{pulls.length > 1 ? 's' : ''}
      </div>
      <div className="space-y-1.5">
        {pulls.map((p) => (
          <div key={p.external_model_id} className="grid grid-cols-[1fr,80px,80px,32px] gap-2 items-center text-xs">
            <div className="truncate font-mono text-white/80">{p.external_model_id}</div>
            <div className="h-1.5 bg-white/8 rounded overflow-hidden">
              <div className="h-full bg-gradient-to-r from-glow-violet to-glow-cyan" style={{ width: `${p.progress_pct}%` }} />
            </div>
            <div className="text-white/55 tabular-nums">{p.progress_pct}%</div>
            <button className="text-white/35 hover:text-glow-pink" title="Cancel">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 4 — Top 3 recommendation shelf
// ─────────────────────────────────────────────────────────────────────

function TopRecommendedShelf({ models, onToggle, onTest, onPin }: {
  models: LocalModel[]
  onToggle: (m: LocalModel) => void
  onTest: (m: LocalModel) => void
  onPin: (m: LocalModel) => void
}) {
  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <div>
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Sparkles size={14} className="text-glow-violet" /> Top {models.length} recommended
          </h2>
          <p className="text-[11px] text-white/40">Best scored models on this machine.</p>
        </div>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {models.map((m) => (
          <article key={m.router_model_id} className="rounded-2xl border border-glow-violet/20 bg-white/[0.03] p-4 relative overflow-hidden">
            <div className="absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r from-glow-violet to-glow-cyan opacity-80" />
            <div className="flex items-start gap-3">
              <div className="w-7 h-7 rounded-lg bg-glow-violet/15 text-glow-violet text-xs font-bold grid place-items-center">
                #{m.rank}
              </div>
              <div className="min-w-0 flex-1">
                <div className="font-bold text-sm leading-tight break-words">
                  {m.display_name || m.external_model_id}
                </div>
                <div className="text-[11px] text-white/45 mt-0.5">
                  {m.family} · {m.parameter_size ?? '?'} · {m.quantization ?? 'fp16'}
                </div>
              </div>
              {m.enabled
                ? <span className="badge-success">Enabled</span>
                : <span className="badge-info">Ready</span>}
            </div>
            <div className="grid grid-cols-2 gap-2 mt-3">
              <Mini label="Score"   value={m.score.toFixed(2)} />
              <Mini label="Latency" value={m.latency_observed_ms ? `${Math.round(m.latency_observed_ms)} ms` : '—'} />
              <Mini label="Context" value={m.context_window?.toString() ?? '—'} />
              <Mini label="Disk"    value={formatBytes(m.disk_size_bytes ?? 0)} />
            </div>
            <div className="flex gap-1.5 flex-wrap mt-3">
              {m.capabilities?.supports_tools && <span className="badge-success">Tools</span>}
              {m.capabilities?.supports_vision && <span className="badge-info">Vision</span>}
              {m.capabilities?.supports_embeddings && <span className="badge-warning">Embeddings</span>}
              {m.pinned && <span className="badge-warning">Pinned</span>}
            </div>
            <div className="flex gap-1.5 mt-3">
              <button className="btn-ghost text-xs" onClick={() => onTest(m)}>
                <HeartPulse size={12} /> Test
              </button>
              <button className="btn-ghost text-xs" onClick={() => onPin(m)}>
                {m.pinned ? <PinOff size={12} /> : <Pin size={12} />}
                {m.pinned ? 'Unpin' : 'Pin'}
              </button>
              <button
                className={m.enabled ? 'btn-danger text-xs ml-auto' : 'btn-primary text-xs ml-auto'}
                onClick={() => onToggle(m)}
              >
                {m.enabled ? 'Disable' : 'Enable'}
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-white/[0.04] p-2">
      <div className="text-[9px] uppercase tracking-wider text-white/35">{label}</div>
      <div className="text-xs font-semibold text-white/85 mt-0.5">{value}</div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 5 — Side rail (hardware + cloud share)
// ─────────────────────────────────────────────────────────────────────

function SideRail({ runtime, stats, manifest, shareLocalDefault, setShareLocalDefault }: any) {
  return (
    <section className="grid lg:grid-cols-2 gap-3">
      <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
        <div className="flex items-center gap-2 mb-2">
          <Cpu size={14} className="text-glow-cyan" />
          <h3 className="text-sm font-semibold">Hardware fit</h3>
        </div>
        <dl className="text-xs text-white/65 space-y-1">
          <Row label="Disk used"   value={formatBytes(stats?.total_disk_bytes ?? 0)} />
          <Row label="Sweet spot"  value="4B–12B parameters" />
          <Row label="Runtime"     value={`${runtime?.runtime ?? '—'} ${runtime?.runtime_base_url ?? ''}`} />
        </dl>
      </div>
      <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
        <div className="flex items-center gap-2 mb-2">
          <Cloud size={14} className="text-glow-violet" />
          <h3 className="text-sm font-semibold">Cloud sharing</h3>
        </div>
        <dl className="text-xs text-white/65 space-y-1">
          <Row label="Bridge"   value={manifest ? 'connected' : 'disconnected'} />
          <Row label="Shared"   value={`${manifest?.stats?.enabled ?? 0} of ${manifest?.stats?.total ?? 0}`} />
          <Row label="Manifest" value={manifest?.stats?.last_sync_at ? `updated ${ago(manifest.stats.last_sync_at)}` : '—'} />
        </dl>
        <label className="flex items-center justify-between mt-3 text-xs">
          <span className="text-white/65">Expose models to cloud</span>
          <input
            type="checkbox"
            checked={shareLocalDefault}
            onChange={(e) => setShareLocalDefault(e.target.checked)}
            className="accent-glow-violet"
          />
        </label>
      </div>
    </section>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-white/40">{label}</dt>
      <dd className="text-right text-white/80 font-mono text-[11px]">{value}</dd>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 6 — Filter bar + bulk drawer
// ─────────────────────────────────────────────────────────────────────

function FilterBar({
  search, setSearch, filter, setFilter, selectedFamilies, setSelectedFamilies,
  sort, setSort,
}: any) {
  const filters: { key: string; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'enabled', label: 'Enabled' },
    { key: 'top', label: 'Top 3' },
    { key: 'tools', label: 'Tools' },
    { key: 'vision', label: 'Vision' },
    { key: 'embeddings', label: 'Embeddings' },
    { key: 'pinned', label: 'Pinned' },
    { key: 'manual', label: 'Manual' },
    { key: 'pulling', label: 'Pulling' },
    { key: 'broken', label: 'Broken' },
    { key: 'removed', label: 'Removed' },
  ]
  const families = ['llama', 'qwen', 'gemma', 'mistral', 'deepseek', 'phi', 'nomic']
  return (
    <section className="sticky top-0 z-10 rounded-2xl border border-white/8 bg-navy-900/85 backdrop-blur p-3 space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {filters.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={[
              'px-3 py-1.5 rounded-full text-xs font-semibold border',
              filter === f.key
                ? 'bg-glow-violet/15 border-glow-violet/40 text-glow-violet'
                : 'bg-white/[0.04] border-white/8 text-white/55 hover:text-white',
            ].join(' ')}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className="flex gap-3 flex-wrap items-center">
        <label className="text-[10px] text-white/45 flex items-center gap-1.5">
          <Filter size={11} /> Family
        </label>
        <div className="flex gap-1 flex-wrap">
          {families.map((fam) => {
            const on = selectedFamilies.has(fam)
            return (
              <button
                key={fam}
                onClick={() => {
                  const next = new Set(selectedFamilies)
                  on ? next.delete(fam) : next.add(fam)
                  setSelectedFamilies(next)
                }}
                className={[
                  'px-2 py-0.5 rounded text-[11px] border',
                  on ? 'bg-glow-cyan/15 border-glow-cyan/40 text-glow-cyan' : 'bg-white/[0.04] border-white/8 text-white/45',
                ].join(' ')}
              >
                {fam}
              </button>
            )
          })}
        </div>
      </div>
      <div className="flex gap-2 items-center">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/35" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search model, family, node…"
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-navy-800/60 border border-white/8 text-sm outline-none focus:border-glow-violet/50"
          />
        </div>
        <div className="flex items-center gap-1.5 text-xs text-white/45">
          <ArrowDownUp size={12} /> Sort
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="px-3 py-2 rounded-lg bg-navy-800/60 border border-white/8 text-sm"
        >
          <option value="score">Best score</option>
          <option value="size_asc">Smallest</option>
          <option value="size_desc">Largest</option>
          <option value="latency">Fastest latency</option>
          <option value="recent">Recently pulled</option>
        </select>
      </div>
    </section>
  )
}

function BulkActionsDrawer({ count, onClear, onEnable, onPin, onTest }: {
  count: number
  onClear: () => void
  onEnable: (on: boolean) => void
  onPin: (on: boolean) => void
  onTest: () => void
}) {
  return (
    <div className="rounded-xl border border-glow-cyan/25 bg-glow-cyan/[0.06] p-2.5 flex items-center gap-2 text-xs">
      <strong className="text-glow-cyan">{count} selected</strong>
      <span className="flex-1" />
      <button className="btn-ghost text-xs" onClick={() => onEnable(true)}>Enable</button>
      <button className="btn-ghost text-xs" onClick={() => onEnable(false)}>Disable</button>
      <button className="btn-ghost text-xs" onClick={() => onPin(true)}>Pin</button>
      <button className="btn-ghost text-xs" onClick={() => onTest()}>Test</button>
      <button className="btn-ghost text-xs" onClick={onClear}>Clear</button>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 7 — Per-node table
// ─────────────────────────────────────────────────────────────────────

function NodeTable({ nodeId, rows, selected, onSelect, onEnable, onPin, onTest, onMetadata, onRemove }: {
  nodeId: string
  rows: LocalModel[]
  selected: Set<string>
  onSelect: (id: string, on: boolean) => void
  onEnable: (m: LocalModel) => void
  onPin: (m: LocalModel) => void
  onTest: (m: LocalModel) => void
  onMetadata: (m: LocalModel) => void
  onRemove: (m: LocalModel) => void
}) {
  return (
    <section className="rounded-2xl border border-white/8 overflow-hidden">
      <header className="px-4 py-2.5 bg-white/[0.04] flex items-center gap-2">
        <HardDrive size={13} className="text-white/45" />
        <h3 className="text-sm font-semibold">{nodeId}</h3>
        <span className="text-xs text-white/40">· {rows.length} model{rows.length === 1 ? '' : 's'}</span>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-white/40">
            <tr>
              <th className="text-left p-2 w-8"></th>
              <th className="text-left p-2 w-10">#</th>
              <th className="text-left p-2">Model</th>
              <th className="text-left p-2">Family</th>
              <th className="text-left p-2">Size</th>
              <th className="text-left p-2">Quant</th>
              <th className="text-left p-2">Context</th>
              <th className="text-left p-2">Caps</th>
              <th className="text-left p-2">Latency</th>
              <th className="text-left p-2">Disk</th>
              <th className="text-left p-2">Status</th>
              <th className="text-left p-2">Share</th>
              <th className="text-right p-2 pr-4">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m: LocalModel) => (
              <tr key={m.router_model_id} className={`border-t border-white/4 hover:bg-white/[0.025] ${selected.has(m.router_model_id) ? 'bg-glow-violet/[0.06]' : ''}`}>
                <td className="p-2">
                  <input
                    type="checkbox"
                    checked={selected.has(m.router_model_id)}
                    onChange={(e) => onSelect(m.router_model_id, e.target.checked)}
                    className="accent-glow-violet"
                  />
                </td>
                <td className="p-2 text-white/55">{m.rank > 0 ? `#${m.rank}` : '—'}</td>
                <td className="p-2 font-mono text-white/85 max-w-[260px] truncate">
                  {m.external_model_id}
                  {m.pinned && <Pin size={10} className="inline ml-1 text-glow-amber" />}
                </td>
                <td className="p-2 text-white/65">{m.family ?? '—'}</td>
                <td className="p-2 text-white/65">{m.parameter_size ?? '—'}</td>
                <td className="p-2 text-white/65">{m.quantization ?? '—'}</td>
                <td className="p-2 text-white/65">{m.context_window?.toLocaleString() ?? '—'}</td>
                <td className="p-2">
                  <span className={m.capabilities?.supports_tools ? 'text-glow-teal' : 'text-white/20'} title="Tools">🛠</span>
                  <span className={m.capabilities?.supports_vision ? 'text-glow-teal' : 'text-white/20'} title="Vision"> 👁</span>
                  <span className={m.capabilities?.supports_embeddings ? 'text-glow-teal' : 'text-white/20'} title="Embeddings"> ≋</span>
                </td>
                <td className="p-2 text-white/65 tabular-nums">{m.latency_observed_ms ? `${Math.round(m.latency_observed_ms)}ms` : '—'}</td>
                <td className="p-2 text-white/65">{formatBytes(m.disk_size_bytes ?? 0)}</td>
                <td className="p-2"><StatusPill status={m.setup_status} /></td>
                <td className="p-2">{m.enabled ? <Eye size={13} className="text-glow-cyan" /> : <EyeOff size={13} className="text-white/25" />}</td>
                <td className="p-2 pr-4">
                  <div className="flex gap-1 justify-end">
                    <RowBtn title={m.enabled ? 'Disable' : 'Enable'} on={m.enabled} onClick={() => onEnable(m)}>
                      {m.enabled ? <ShieldCheck size={12} /> : <CheckCircle2 size={12} />}
                    </RowBtn>
                    <RowBtn title="Test"      onClick={() => onTest(m)}><HeartPulse size={12} /></RowBtn>
                    <RowBtn title={m.pinned ? 'Unpin' : 'Pin'} on={m.pinned} onClick={() => onPin(m)}>
                      {m.pinned ? <PinOff size={12} /> : <Pin size={12} />}
                    </RowBtn>
                    <RowBtn title="Metadata"  onClick={() => onMetadata(m)}><ChevronDown size={12} /></RowBtn>
                    {m.manually_added && (
                      <RowBtn title="Delete manual" danger onClick={() => onRemove(m)}><Trash2 size={12} /></RowBtn>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function StatusPill({ status }: { status: LocalModel['setup_status'] }) {
  const tone: Record<LocalModel['setup_status'], string> = {
    verified:      'bg-glow-teal/15 text-glow-teal border-glow-teal/30',
    broken:        'bg-glow-pink/15 text-glow-pink border-glow-pink/30',
    pulling:       'bg-glow-cyan/15 text-glow-cyan border-glow-cyan/30',
    auto:          'bg-glow-amber/12 text-glow-amber border-glow-amber/30',
    disabled:      'bg-white/[0.04] text-white/45 border-white/10',
    not_installed: 'bg-white/[0.04] text-white/45 border-white/10',
    removed:       'bg-white/[0.04] text-white/35 border-white/8',
  }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${tone[status]} uppercase font-semibold tracking-wider`}>
      {status}
    </span>
  )
}

function RowBtn({ children, title, onClick, on, danger }: any) {
  const cls = on
    ? 'border-glow-teal/40 text-glow-teal bg-glow-teal/8'
    : danger
      ? 'border-white/10 text-white/55 hover:border-glow-pink/40 hover:text-glow-pink'
      : 'border-white/10 text-white/65 hover:border-glow-violet/40 hover:text-white'
  return (
    <button title={title} onClick={onClick} className={`w-6 h-6 rounded-md border grid place-items-center ${cls}`}>
      {children}
    </button>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 8 — Pull gallery
// ─────────────────────────────────────────────────────────────────────

function PullGallery({ installed, active, onPull, onPullCustom }: {
  installed: Set<string>
  active: Set<string>
  onPull: (tag: string) => void
  onPullCustom: () => void
}) {
  return (
    <section>
      <header className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold">Pull from library</h3>
        <button className="btn-ghost text-xs" onClick={onPullCustom}>
          <Plus size={12} /> Pull custom tag
        </button>
      </header>
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
        {RECOMMENDED_TAGS.map((r) => {
          const state = active.has(r.tag) ? 'pulling' : installed.has(r.tag) ? 'installed' : 'available'
          return (
            <div key={r.tag} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <div className="text-sm font-semibold">{r.title}</div>
              <div className="text-[11px] text-white/45 font-mono mt-0.5">{r.tag}</div>
              <div className="flex gap-1 mt-2 flex-wrap">
                <span className="badge-info">{r.size_label}</span>
                <span className="badge-info">{r.approx_gb}</span>
                {r.tags.map((t) => <span key={t} className="badge-warning">{t}</span>)}
              </div>
              {state === 'available' && (
                <button className="btn-primary text-xs mt-3 w-full" onClick={() => onPull(r.tag)}>
                  <Download size={12} /> Pull
                </button>
              )}
              {state === 'pulling' && (
                <button className="btn-ghost text-xs mt-3 w-full" disabled>
                  <Loader2 size={12} className="animate-spin" /> Pulling…
                </button>
              )}
              {state === 'installed' && (
                <button className="btn-ghost text-xs mt-3 w-full" disabled>
                  <CheckCircle2 size={12} className="text-glow-teal" /> Installed
                </button>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 9 — Empty state + banners
// ─────────────────────────────────────────────────────────────────────

function EmptyCatalogState({ onPullRecommended, onPullCustom, onAddManual }: any) {
  return (
    <section className="rounded-3xl border border-white/8 bg-white/[0.02] p-12 text-center">
      <div className="w-16 h-16 mx-auto mb-4 rounded-3xl bg-glow-violet/12 border border-glow-violet/25 grid place-items-center text-glow-violet">
        <Sparkles size={28} />
      </div>
      <h2 className="text-lg font-bold">No local models yet</h2>
      <p className="text-sm text-white/50 mt-1 max-w-md mx-auto">
        Start with the recommended set or pull a custom tag — OllaBridge will
        score them and auto-enable the best three.
      </p>
      <div className="flex gap-2 justify-center mt-5 flex-wrap">
        <button className="btn-primary" onClick={onPullRecommended}>
          <Download size={14} /> Pull recommended top 3
        </button>
        <button className="btn-ghost" onClick={onPullCustom}>
          <Plus size={14} /> Pull custom tag
        </button>
        <button className="btn-ghost" onClick={onAddManual}>
          <Plus size={14} /> Add manually
        </button>
      </div>
    </section>
  )
}

function RuntimeDownBanner({ runtime }: { runtime: any }) {
  return (
    <div className="rounded-2xl border border-glow-pink/30 bg-glow-pink/8 p-4 flex items-start gap-3">
      <AlertTriangle size={18} className="text-glow-pink mt-0.5" />
      <div className="flex-1">
        <strong className="text-glow-pink">Ollama is not responding.</strong>
        <p className="text-xs text-white/55 mt-1">
          Tried <code className="font-mono">{runtime.runtime_base_url}</code>. Start the service or
          adjust the runtime URL on Settings.
        </p>
      </div>
      <button className="btn-ghost text-xs">Settings</button>
      <button className="btn-ghost text-xs">Retry</button>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SECTION 10 — Modal stubs
// ─────────────────────────────────────────────────────────────────────

function ModalBackdrop({ children, onClose }: any) {
  return (
    <div
      className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm grid place-items-center p-4"
      onClick={onClose}
    >
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-xl">{children}</div>
    </div>
  )
}

type ManualAddPayload = {
  node_id: string
  external_model_id: string
  runtime?: string
  display_name?: string
  enabled?: boolean
  pinned?: boolean
  supports_tools?: boolean
  supports_vision?: boolean
  supports_embeddings?: boolean
}

function ManualAddModal({ nodes, onClose, onSubmit }: {
  nodes: string[]
  onClose: () => void
  onSubmit: (payload: ManualAddPayload) => void
}) {
  const [node, setNode] = useState(nodes[0] ?? 'local')
  const [tag, setTag] = useState('')
  const [tools, setTools] = useState(false)
  const [vision, setVision] = useState(false)
  const [embed, setEmbed] = useState(false)
  const [enabled, setEnabled] = useState(true)
  return (
    <ModalBackdrop onClose={onClose}>
      <div className="rounded-2xl border border-white/10 bg-navy-900 p-5 space-y-3">
        <h3 className="text-base font-bold">Add a local model</h3>
        <Field label="Node">
          <select value={node} onChange={(e) => setNode(e.target.value)} className="modal-input">
            {nodes.map((n: string) => <option key={n} value={n}>{n}</option>)}
          </select>
        </Field>
        <Field label="Model tag">
          <input className="modal-input" value={tag} onChange={(e) => setTag(e.target.value)} placeholder="qwen2.5:14b" />
        </Field>
        <div className="flex flex-wrap gap-3 text-xs">
          <Check value={tools}   setValue={setTools}   label="Supports tools" />
          <Check value={vision}  setValue={setVision}  label="Supports vision" />
          <Check value={embed}   setValue={setEmbed}   label="Embeddings model" />
          <Check value={enabled} setValue={setEnabled} label="Enable immediately" />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            onClick={() => onSubmit({
              node_id: node, external_model_id: tag.trim(),
              supports_tools: tools, supports_vision: vision, supports_embeddings: embed,
              enabled,
            })}
          >
            Add
          </button>
        </div>
      </div>
    </ModalBackdrop>
  )
}

function PullProgressModal({ initialTag, nodeId, onClose, onStart }: {
  initialTag: string
  nodeId?: string
  onClose: () => void
  onStart: (tag: string) => void
}) {
  const [tag, setTag] = useState(initialTag)
  const [started, setStarted] = useState(false)
  return (
    <ModalBackdrop onClose={onClose}>
      <div className="rounded-2xl border border-white/10 bg-navy-900 p-5 space-y-3">
        <h3 className="text-base font-bold">Pull a model</h3>
        <Field label="Model tag">
          <input
            className="modal-input font-mono"
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            placeholder="qwen2.5:14b"
            disabled={started}
          />
        </Field>
        {started && (
          <p className="text-xs text-white/55">
            Pull started. Progress will appear in the banner above; you can close
            this modal at any time.
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button className="btn-ghost" onClick={onClose}>{started ? 'Close' : 'Cancel'}</button>
          {!started && (
            <button
              className="btn-primary"
              disabled={!tag.trim()}
              onClick={() => { onStart(tag.trim()); setStarted(true) }}
            >
              Start pull
            </button>
          )}
        </div>
        {void nodeId}
      </div>
    </ModalBackdrop>
  )
}

function TestResultModal({ routerId, onClose }: any) {
  const test = useTestLocalModel()
  return (
    <ModalBackdrop onClose={onClose}>
      <div className="rounded-2xl border border-white/10 bg-navy-900 p-5 space-y-3">
        <h3 className="text-base font-bold">Test model</h3>
        <p className="text-xs text-white/55 font-mono">{routerId}</p>
        {test.data && (
          <div className="rounded-xl border border-white/8 p-3 text-xs space-y-1">
            <div>Status: <strong className={test.data.ok ? 'text-glow-teal' : 'text-glow-pink'}>{test.data.setup_status}</strong></div>
            <div>Latency: <strong className="tabular-nums">{test.data.latency_ms ? `${Math.round(test.data.latency_ms)} ms` : '—'}</strong></div>
            {test.data.error && <div>Error: <strong className="text-glow-pink">{test.data.error}</strong></div>}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button className="btn-ghost" onClick={onClose}>Close</button>
          <button
            className="btn-primary"
            onClick={() => test.mutate(routerId)}
            disabled={test.isPending}
          >
            {test.isPending ? <Loader2 size={12} className="animate-spin" /> : <HeartPulse size={12} />}
            Run probe
          </button>
        </div>
      </div>
    </ModalBackdrop>
  )
}

function RawMetadataModal({ model, onClose }: { model?: LocalModel; onClose: () => void }) {
  return (
    <ModalBackdrop onClose={onClose}>
      <div className="rounded-2xl border border-white/10 bg-navy-900 p-5 space-y-3 max-h-[80vh] overflow-auto">
        <h3 className="text-base font-bold">Model metadata</h3>
        {model ? (
          <pre className="text-[11px] bg-black/40 rounded-lg p-3 overflow-auto text-white/75">
            {JSON.stringify(model, null, 2)}
          </pre>
        ) : <p className="text-xs text-white/50">Model not found.</p>}
        <div className="flex justify-end pt-2">
          <button className="btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </ModalBackdrop>
  )
}

function ConfirmRemoveModal({ routerId, onClose, onConfirm }: any) {
  return (
    <ModalBackdrop onClose={onClose}>
      <div className="rounded-2xl border border-glow-pink/30 bg-navy-900 p-5 space-y-3">
        <h3 className="text-base font-bold">Delete manual row?</h3>
        <p className="text-xs text-white/55">
          This removes <code className="font-mono">{routerId}</code> from the catalog only.
          The model file on disk is left untouched — run <code className="font-mono">ollama rm</code> for that.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-danger" onClick={onConfirm}>Delete</button>
        </div>
      </div>
    </ModalBackdrop>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────

function Field({ label, children }: any) {
  return (
    <label className="block text-xs">
      <span className="text-white/45 uppercase tracking-wider text-[10px]">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  )
}

function Check({ value, setValue, label }: any) {
  return (
    <label className="flex items-center gap-1.5 text-white/75">
      <input type="checkbox" checked={value} onChange={(e) => setValue(e.target.checked)} className="accent-glow-violet" />
      {label}
    </label>
  )
}

function formatBytes(bytes: number): string {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(n >= 100 ? 0 : 1)} ${units[i]}`
}

function ago(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}
