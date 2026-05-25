import { useState, useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  PlugZap,
  KeyRound,
  RefreshCw,
  Search,
  Sparkles,
  Eye,
  EyeOff,
  Check,
  AlertTriangle,
  Lock,
  Cpu,
  Zap,
  Brain,
  ImageIcon,
  Video,
  Wrench,
  Braces,
  TrendingUp,
  Boxes,
  Activity,
  ShieldCheck,
  Copy,
  CheckCircle2,
  XCircle,
  Loader2,
  ExternalLink,
} from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  useHFRecommendations,
  useHFStatus,
  useHFModels,
  useProvidersAliases,
  useProvidersList,
} from '../../lib/hooks'
import { api, type HFCatalogEntry, type ProviderSummary } from '../../lib/api'

// ── Tabs ─────────────────────────────────────────────────────────

type Tab = 'connect' | 'discover' | 'route' | 'usage'

const TABS: { id: Tab; label: string; icon: typeof PlugZap; description: string }[] = [
  { id: 'connect', label: 'Connect', icon: KeyRound, description: 'Hugging Face token & billing' },
  { id: 'discover', label: 'Discover', icon: Search, description: 'Browse the live model catalog' },
  { id: 'route', label: 'Route', icon: Sparkles, description: 'Intent aliases & routing policy' },
  { id: 'usage', label: 'Usage', icon: Activity, description: 'Health, latency, fail-overs' },
]

// ── Re-usable primitives ────────────────────────────────────────

function GlassCard({
  children,
  className = '',
  delay = 0,
}: {
  children: React.ReactNode
  className?: string
  delay?: number
}) {
  return (
    <motion.div
      className={`glass-card p-6 ${className}`}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay }}
    >
      {children}
    </motion.div>
  )
}

function SectionTitle({
  icon: Icon,
  title,
  subtitle,
  color = '#00e5ff',
  badge,
}: {
  icon: typeof PlugZap
  title: string
  subtitle?: string
  color?: string
  badge?: { label: string; color: string }
}) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
        style={{
          background: `linear-gradient(135deg, ${color}20, ${color}08)`,
          border: `1px solid ${color}30`,
        }}
      >
        <Icon size={18} style={{ color }} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h2 className="text-white/90 font-semibold text-base truncate">{title}</h2>
          {badge && (
            <span
              className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
              style={{
                background: `${badge.color}15`,
                color: badge.color,
                border: `1px solid ${badge.color}30`,
              }}
            >
              {badge.label}
            </span>
          )}
        </div>
        {subtitle && <p className="text-white/40 text-xs mt-0.5 truncate">{subtitle}</p>}
      </div>
    </div>
  )
}

function CopyChip({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-mono transition-colors"
      style={{
        background: copied ? 'rgba(20,184,166,0.15)' : 'rgba(255,255,255,0.04)',
        border: copied ? '1px solid rgba(20,184,166,0.35)' : '1px solid rgba(255,255,255,0.08)',
        color: copied ? '#14b8a6' : 'rgba(255,255,255,0.75)',
      }}
    >
      {copied ? <Check size={11} /> : <Copy size={11} />}
      <span>{label ?? text}</span>
    </button>
  )
}

const HEALTH_COLORS: Record<string, string> = {
  healthy: '#14b8a6',
  degraded: '#f59e0b',
  down: '#ef4444',
  maintenance: '#6b7280',
  quota_exhausted: '#ec4899',
  unknown: '#64748b',
}

function HealthDot({ health }: { health: string }) {
  const color = HEALTH_COLORS[health] || '#64748b'
  return (
    <div className="relative inline-flex">
      <div className="w-2 h-2 rounded-full" style={{ background: color }} />
      {health === 'healthy' && (
        <div
          className="absolute inset-0 w-2 h-2 rounded-full animate-ping"
          style={{ background: color, opacity: 0.4 }}
        />
      )}
    </div>
  )
}

// ── Tab: Connect ────────────────────────────────────────────────

function ConnectTab() {
  const { data: status } = useHFStatus()
  const queryClient = useQueryClient()
  const [token, setToken] = useState('')
  const [billTo, setBillTo] = useState('')
  const [mode, setMode] = useState<'free_credit_only' | 'allow_paid' | 'provider_keys'>(
    'free_credit_only',
  )
  const [showToken, setShowToken] = useState(false)

  const connect = useMutation({
    mutationFn: () =>
      api.hfConnect({ token: token.trim(), bill_to: billTo.trim() || undefined, mode }),
    onSuccess: () => {
      setToken('')
      queryClient.invalidateQueries({ queryKey: ['hfStatus'] })
      queryClient.invalidateQueries({ queryKey: ['providersList'] })
    },
  })

  const disconnect = useMutation({
    mutationFn: () => api.hfDisconnect(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hfStatus'] })
      queryClient.invalidateQueries({ queryKey: ['providersList'] })
    },
  })

  const refresh = useMutation({
    mutationFn: () => api.hfRefresh({ limit: 100, profile: 'free_lab' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hfStatus'] })
      queryClient.invalidateQueries({ queryKey: ['providersAliases'] })
      queryClient.invalidateQueries({ queryKey: ['hfModels'] })
      queryClient.invalidateQueries({ queryKey: ['hfRecommendations'] })
    },
  })

  const connected = !!status?.connected

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Connection card */}
      <GlassCard className="lg:col-span-2">
        <SectionTitle
          icon={KeyRound}
          title="Hugging Face account"
          subtitle="Your token routes requests across Together, Groq, Novita, Fireworks, DeepInfra and more."
          color="#fbbf24"
          badge={
            connected
              ? { label: 'Connected', color: '#14b8a6' }
              : { label: 'Not connected', color: '#64748b' }
          }
        />

        {!connected ? (
          <div className="space-y-4">
            <div>
              <label className="block text-[11px] uppercase tracking-wider text-white/40 font-medium mb-1.5">
                HF access token
              </label>
              <div className="relative">
                <input
                  type={showToken ? 'text' : 'password'}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="hf_xxxxxxxxxxxxxxxxxxxxxxxx"
                  className="w-full bg-navy-800/60 border border-white/10 rounded-lg px-3 py-2.5 pr-10 text-sm font-mono text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
                  spellCheck={false}
                  autoComplete="off"
                />
                <button
                  type="button"
                  onClick={() => setShowToken((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-md text-white/40 hover:text-white/70 hover:bg-white/5 transition-colors"
                >
                  {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <p className="text-[11px] text-white/40 mt-1.5 leading-relaxed">
                Create one at{' '}
                <a
                  href="https://huggingface.co/settings/tokens"
                  target="_blank"
                  rel="noreferrer"
                  className="text-glow-cyan hover:underline inline-flex items-center gap-0.5"
                >
                  huggingface.co/settings/tokens
                  <ExternalLink size={9} />
                </a>{' '}
                with the <span className="font-mono text-white/60">inference.serverless.write</span> scope.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] uppercase tracking-wider text-white/40 font-medium mb-1.5">
                  Bill to org (optional)
                </label>
                <input
                  type="text"
                  value={billTo}
                  onChange={(e) => setBillTo(e.target.value)}
                  placeholder="my-org-slug"
                  className="w-full bg-navy-800/60 border border-white/10 rounded-lg px-3 py-2.5 text-sm font-mono text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
                />
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-wider text-white/40 font-medium mb-1.5">
                  Spend policy
                </label>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value as typeof mode)}
                  className="w-full bg-navy-800/60 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white focus:outline-none focus:border-glow-cyan/40 transition-colors"
                >
                  <option value="free_credit_only">Free-credit only (hard-stop on 402)</option>
                  <option value="allow_paid">Allow paid after warning</option>
                  <option value="provider_keys">Custom provider keys</option>
                </select>
              </div>
            </div>

            <div className="flex items-center justify-between pt-2">
              <div className="flex items-center gap-2 text-[11px] text-white/40">
                <Lock size={12} />
                <span>Encrypted at rest via Fernet (HKDF from OLLA_SECRET)</span>
              </div>
              <button
                onClick={() => connect.mutate()}
                disabled={!token.trim() || connect.isPending}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-glow-cyan/20 border border-glow-cyan/40 text-glow-cyan hover:bg-glow-cyan/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {connect.isPending ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
                Connect
              </button>
            </div>

            {connect.isError && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                <span>{(connect.error as Error).message}</span>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="px-3 py-2.5 rounded-lg bg-navy-800/50 border border-white/5">
                <div className="text-[10px] uppercase tracking-wider text-white/40 mb-0.5">Mode</div>
                <div className="text-white/85 text-sm font-medium">
                  {status?.mode === 'free_credit_only'
                    ? 'Free-credit only'
                    : status?.mode === 'allow_paid'
                    ? 'Allow paid'
                    : 'Provider keys'}
                </div>
              </div>
              <div className="px-3 py-2.5 rounded-lg bg-navy-800/50 border border-white/5">
                <div className="text-[10px] uppercase tracking-wider text-white/40 mb-0.5">
                  Bill to
                </div>
                <div className="text-white/85 text-sm font-medium font-mono truncate">
                  {status?.bill_to || '—'}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 text-[11px] text-white/40">
              {status?.encrypted_at_rest ? (
                <>
                  <ShieldCheck size={12} className="text-emerald-400" />
                  <span>Token encrypted at rest under ~/.ollabridge/secrets.enc</span>
                </>
              ) : (
                <>
                  <AlertTriangle size={12} className="text-amber-400" />
                  <span>
                    Plaintext mode — set <span className="font-mono">OLLA_SECRET</span> to enable encryption.
                  </span>
                </>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => refresh.mutate()}
                disabled={refresh.isPending}
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium bg-glow-cyan/15 border border-glow-cyan/30 text-glow-cyan hover:bg-glow-cyan/25 transition-colors disabled:opacity-40"
              >
                {refresh.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <RefreshCw size={14} />
                )}
                Refresh catalog
              </button>
              <button
                onClick={() => disconnect.mutate()}
                disabled={disconnect.isPending}
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium bg-red-500/10 border border-red-500/25 text-red-300 hover:bg-red-500/20 transition-colors disabled:opacity-40"
              >
                Disconnect
              </button>
            </div>

            {refresh.isError && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                <span>{(refresh.error as Error).message}</span>
              </div>
            )}
          </div>
        )}
      </GlassCard>

      {/* Catalog summary */}
      <GlassCard delay={0.08}>
        <SectionTitle
          icon={Boxes}
          title="Catalog"
          subtitle="Live Hugging Face routes"
          color="#8b5cf6"
        />
        <div className="space-y-3">
          <div className="px-3 py-3 rounded-lg bg-gradient-to-br from-violet-500/10 to-cyan-500/5 border border-violet-500/20">
            <div className="text-[10px] uppercase tracking-wider text-white/40 mb-0.5">
              Catalog rows
            </div>
            <div className="text-white text-3xl font-bold">{status?.catalog.entries ?? '—'}</div>
            <div className="text-[11px] text-white/40 mt-0.5">model:provider pairs</div>
          </div>
          {status?.catalog.last_sync ? (
            <div className="px-3 py-2.5 rounded-lg bg-navy-800/50 border border-white/5 text-[11px] space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-white/40">Last sync</span>
                <span className="text-white/70 font-mono">
                  {new Date(status.catalog.last_sync.finished_at).toLocaleString()}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-white/40">Duration</span>
                <span className="text-white/70 font-mono">
                  {status.catalog.last_sync.duration_s.toFixed(2)}s
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-white/40">Fetched / upserted</span>
                <span className="text-white/70 font-mono">
                  {status.catalog.last_sync.fetched} / {status.catalog.last_sync.upserted}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-white/40">Aliases rewritten</span>
                <span className="text-glow-cyan font-mono">
                  {status.catalog.last_sync.aliases_written}
                </span>
              </div>
              {status.catalog.last_sync.error && (
                <div className="text-red-300 mt-1 truncate">
                  {status.catalog.last_sync.error}
                </div>
              )}
            </div>
          ) : (
            <div className="text-[11px] text-white/40">
              No sync yet. Connect a token and refresh to populate the catalog.
            </div>
          )}
        </div>
      </GlassCard>
    </div>
  )
}

// ── Tab: Discover ───────────────────────────────────────────────

const TASK_OPTIONS = [
  { value: '', label: 'All tasks' },
  { value: 'chat-completion', label: 'Chat completion' },
  { value: 'vlm', label: 'Vision-language' },
  { value: 'image-generation', label: 'Image generation' },
  { value: 'video-generation', label: 'Video generation' },
]

function CapabilityBadge({
  on,
  label,
  color,
}: {
  on: boolean
  label: string
  color: string
}) {
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
      style={{
        background: on ? `${color}18` : 'rgba(255,255,255,0.03)',
        color: on ? color : 'rgba(255,255,255,0.25)',
        border: `1px solid ${on ? `${color}30` : 'rgba(255,255,255,0.06)'}`,
      }}
    >
      {label}
    </span>
  )
}

function ModelRow({ row }: { row: HFCatalogEntry }) {
  const costMarker = useMemo(() => {
    const a = row.input_price_per_1m ?? 0
    const b = row.output_price_per_1m ?? 0
    if (row.input_price_per_1m === null && row.output_price_per_1m === null) return 'unknown'
    if (a === 0 && b === 0) return 'free'
    if (Math.max(a, b) < 1.0) return 'cheap'
    return 'paid'
  }, [row])
  const costColors: Record<string, string> = {
    free: '#14b8a6',
    cheap: '#22d3ee',
    paid: '#f59e0b',
    unknown: '#64748b',
  }
  return (
    <div className="grid grid-cols-12 gap-3 items-center px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors border border-white/[0.03]">
      <div className="col-span-5 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-white/30 w-6 text-right">#{row.rank}</span>
          <div className="min-w-0">
            <div className="text-white/90 text-sm font-medium truncate">{row.model_id}</div>
            <div className="text-[11px] text-white/40 font-mono truncate">{row.router_model_id}</div>
          </div>
        </div>
      </div>
      <div className="col-span-2 flex items-center gap-1.5">
        <CapabilityBadge on={row.supports_tools} label="tools" color="#22d3ee" />
        <CapabilityBadge on={row.supports_structured_output} label="json" color="#8b5cf6" />
      </div>
      <div className="col-span-1 text-right">
        <span
          className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
          style={{
            background: `${costColors[costMarker]}18`,
            color: costColors[costMarker],
            border: `1px solid ${costColors[costMarker]}30`,
          }}
        >
          {costMarker}
        </span>
      </div>
      <div className="col-span-1 text-right text-[11px] text-white/60 font-mono">
        {row.context_window ? `${(row.context_window / 1000).toFixed(0)}k` : '—'}
      </div>
      <div className="col-span-1 text-right text-[11px] text-white/60 font-mono">
        {row.latency_s ? `${(row.latency_s * 1000).toFixed(0)}ms` : '—'}
      </div>
      <div className="col-span-1 text-right text-[11px] text-white/60 font-mono">
        {row.throughput_tps ? `${row.throughput_tps.toFixed(0)} t/s` : '—'}
      </div>
      <div className="col-span-1 text-right">
        <span className="text-[11px] font-mono text-glow-cyan font-semibold">
          {row.score.toFixed(3)}
        </span>
      </div>
    </div>
  )
}

function DiscoverTab() {
  const [task, setTask] = useState('')
  const [supportsTools, setSupportsTools] = useState(false)
  const [supportsJson, setSupportsJson] = useState(false)
  const [freeOnly, setFreeOnly] = useState(true)
  const [query, setQuery] = useState('')

  const params = useMemo(
    () => ({
      task: task || undefined,
      supports_tools: supportsTools || undefined,
      supports_structured_output: supportsJson || undefined,
      free_credit_only: freeOnly || undefined,
      limit: 200,
    }),
    [task, supportsTools, supportsJson, freeOnly],
  )

  const { data, isLoading, isError, error } = useHFModels(params)
  const filtered = useMemo(() => {
    const all = data?.models ?? []
    if (!query.trim()) return all
    const q = query.toLowerCase()
    return all.filter(
      (m) => m.model_id.toLowerCase().includes(q) || m.hf_provider.toLowerCase().includes(q),
    )
  }, [data, query])

  return (
    <GlassCard>
      <SectionTitle
        icon={Search}
        title="Model Explorer"
        subtitle="Top inference-capable models served by Hugging Face Inference Providers."
        color="#22d3ee"
        badge={
          data
            ? { label: `${filtered.length} of ${data.total}`, color: '#22d3ee' }
            : undefined
        }
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select
          value={task}
          onChange={(e) => setTask(e.target.value)}
          className="bg-navy-800/60 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-glow-cyan/40 transition-colors"
        >
          {TASK_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <ToggleChip on={supportsTools} onClick={() => setSupportsTools((v) => !v)} icon={Wrench} label="Tools" color="#22d3ee" />
        <ToggleChip on={supportsJson} onClick={() => setSupportsJson((v) => !v)} icon={Braces} label="JSON" color="#8b5cf6" />
        <ToggleChip on={freeOnly} onClick={() => setFreeOnly((v) => !v)} icon={ShieldCheck} label="Free-credit only" color="#14b8a6" />

        <div className="relative flex-1 min-w-[180px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/30" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search model or upstream provider..."
            className="w-full bg-navy-800/60 border border-white/10 rounded-lg pl-7 pr-3 py-1.5 text-xs text-white placeholder:text-white/30 focus:outline-none focus:border-glow-cyan/40 transition-colors"
          />
        </div>
      </div>

      {/* Header row */}
      <div className="grid grid-cols-12 gap-3 px-3 py-2 text-[10px] uppercase tracking-wider text-white/30 font-semibold border-b border-white/5">
        <div className="col-span-5">Model</div>
        <div className="col-span-2">Capabilities</div>
        <div className="col-span-1 text-right">Cost</div>
        <div className="col-span-1 text-right">Ctx</div>
        <div className="col-span-1 text-right">Lat</div>
        <div className="col-span-1 text-right">T/s</div>
        <div className="col-span-1 text-right">Score</div>
      </div>

      {/* Rows */}
      <div className="space-y-1 mt-2 max-h-[600px] overflow-y-auto pr-1">
        {isLoading && (
          <div className="px-3 py-6 text-center text-white/40 text-sm flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading catalog…
          </div>
        )}
        {isError && (
          <div className="px-3 py-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
            {(error as Error).message}
          </div>
        )}
        {!isLoading && !isError && filtered.length === 0 && (
          <div className="px-3 py-6 text-center text-white/40 text-sm">
            No rows match. Try widening the filters or running a catalog refresh.
          </div>
        )}
        {filtered.map((row) => (
          <ModelRow key={row.router_model_id} row={row} />
        ))}
      </div>
    </GlassCard>
  )
}

function ToggleChip({
  on,
  onClick,
  icon: Icon,
  label,
  color,
}: {
  on: boolean
  onClick: () => void
  icon: typeof Wrench
  label: string
  color: string
}) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors"
      style={{
        background: on ? `${color}18` : 'rgba(255,255,255,0.03)',
        color: on ? color : 'rgba(255,255,255,0.5)',
        border: `1px solid ${on ? `${color}40` : 'rgba(255,255,255,0.08)'}`,
      }}
    >
      <Icon size={12} />
      {label}
    </button>
  )
}

// ── Tab: Route ──────────────────────────────────────────────────

const BUCKET_META: Record<string, { icon: typeof Zap; color: string; description: string }> = {
  'ollabridge:auto': { icon: Sparkles, color: '#00e5ff', description: 'Best overall route' },
  'ollabridge:fast': { icon: Zap, color: '#facc15', description: 'Lowest latency' },
  'ollabridge:reasoning': { icon: Brain, color: '#8b5cf6', description: 'Best reasoning' },
  'ollabridge:vision': { icon: Eye, color: '#ec4899', description: 'Image understanding' },
  'ollabridge:tools': { icon: Wrench, color: '#22d3ee', description: 'Tool calling' },
  'ollabridge:json': { icon: Braces, color: '#a78bfa', description: 'Structured output' },
  'ollabridge:image': { icon: ImageIcon, color: '#f472b6', description: 'Image generation' },
  'ollabridge:video': { icon: Video, color: '#fb7185', description: 'Video generation' },
  'ollabridge:free': { icon: ShieldCheck, color: '#14b8a6', description: 'No-paid-usage only' },
  'ollabridge:private': { icon: Lock, color: '#94a3b8', description: 'Local only' },
  'hf:best': { icon: TrendingUp, color: '#fbbf24', description: 'Top HF chat route' },
  'hf:fast': { icon: Zap, color: '#facc15', description: 'Lowest HF latency' },
  'hf:cheap': { icon: ShieldCheck, color: '#14b8a6', description: 'Cheapest HF route' },
  'hf:deepseek': { icon: TrendingUp, color: '#22d3ee', description: 'DeepSeek family' },
  'hf:vision': { icon: Eye, color: '#ec4899', description: 'HF vision-language' },
  'hf:tools': { icon: Wrench, color: '#22d3ee', description: 'HF tool-calling' },
  'hf:image': { icon: ImageIcon, color: '#f472b6', description: 'HF image gen' },
  'hf:video': { icon: Video, color: '#fb7185', description: 'HF video gen' },
  'hf:auto': { icon: Sparkles, color: '#00e5ff', description: 'HF best overall' },
}

function AliasCard({ alias, candidates }: { alias: string; candidates: { provider: string; model: string }[] }) {
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<
    | { ok: true; latency: number; excerpt: string; chose: string }
    | { ok: false; error: string }
    | null
  >(null)
  const meta = BUCKET_META[alias] ?? { icon: Boxes, color: '#64748b', description: 'Custom alias' }
  const Icon = meta.icon

  const runTest = useCallback(async () => {
    setTesting(true)
    setResult(null)
    const started = performance.now()
    try {
      const res = await api.providersTest({ model: alias, prompt: 'ping', max_tokens: 8 })
      const latency = performance.now() - started
      setResult({
        ok: true,
        latency,
        chose: `${res.chose.provider_id} → ${res.chose.model}`,
        excerpt: res.response.choices[0]?.message?.content?.slice(0, 80) ?? '',
      })
    } catch (e) {
      setResult({ ok: false, error: (e as Error).message })
    } finally {
      setTesting(false)
    }
  }, [alias])

  return (
    <div className="px-4 py-3 rounded-xl bg-navy-800/40 border border-white/5 hover:border-white/10 transition-colors">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
            style={{
              background: `linear-gradient(135deg, ${meta.color}20, ${meta.color}06)`,
              border: `1px solid ${meta.color}30`,
            }}
          >
            <Icon size={14} style={{ color: meta.color }} />
          </div>
          <div className="min-w-0">
            <div className="text-white/90 text-sm font-semibold font-mono truncate">{alias}</div>
            <div className="text-[11px] text-white/40 truncate">{meta.description}</div>
          </div>
        </div>
        <button
          onClick={runTest}
          disabled={testing}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium bg-glow-cyan/10 border border-glow-cyan/25 text-glow-cyan hover:bg-glow-cyan/20 transition-colors disabled:opacity-40"
        >
          {testing ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
          Test
        </button>
      </div>
      <div className="space-y-1 max-h-24 overflow-y-auto">
        {candidates.slice(0, 3).map((c, i) => (
          <div key={`${c.provider}/${c.model}/${i}`} className="flex items-center gap-2 px-2 py-1 rounded bg-navy-900/40">
            <span className="text-[10px] text-white/30 w-4">{i + 1}</span>
            <span className="text-[11px] font-mono text-white/65 truncate flex-1">{c.model}</span>
            <span className="text-[10px] text-white/30">via {c.provider}</span>
          </div>
        ))}
      </div>
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-2"
          >
            {result.ok ? (
              <div className="px-2 py-1.5 rounded-md bg-emerald-500/8 border border-emerald-500/25 text-[11px]">
                <div className="flex items-center gap-1.5 text-emerald-300 mb-0.5">
                  <CheckCircle2 size={11} />
                  <span className="font-semibold">{result.latency.toFixed(0)}ms</span>
                  <span className="text-white/40">via</span>
                  <span className="font-mono text-white/70 truncate">{result.chose}</span>
                </div>
                {result.excerpt && (
                  <div className="text-white/55 italic truncate">"{result.excerpt}"</div>
                )}
              </div>
            ) : (
              <div className="px-2 py-1.5 rounded-md bg-red-500/8 border border-red-500/25 text-[11px] text-red-300 flex items-start gap-1.5">
                <XCircle size={11} className="shrink-0 mt-0.5" />
                <span className="truncate">{result.error}</span>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function RouteTab() {
  const { data: rec } = useHFRecommendations(3)
  const { data: aliases } = useProvidersAliases()

  const buckets = rec?.buckets ?? {}
  const aliasMap = aliases?.aliases ?? {}

  const allAliases = useMemo(() => {
    // Prefer dynamic bucket order; append non-managed manual aliases at the end.
    const seen = new Set<string>()
    const out: { alias: string; candidates: { provider: string; model: string }[] }[] = []
    for (const [alias, candidates] of Object.entries(buckets)) {
      out.push({ alias, candidates: candidates as { provider: string; model: string }[] })
      seen.add(alias)
    }
    for (const [alias, candidates] of Object.entries(aliasMap)) {
      if (seen.has(alias)) continue
      out.push({ alias, candidates })
    }
    return out
  }, [buckets, aliasMap])

  return (
    <GlassCard>
      <SectionTitle
        icon={Sparkles}
        title="Intent aliases"
        subtitle="Stable names for client SDKs. Underlying model rotates as the catalog refreshes."
        color="#8b5cf6"
        badge={{ label: `${allAliases.length} aliases`, color: '#8b5cf6' }}
      />

      <div className="mb-4 px-3 py-2.5 rounded-lg bg-glow-cyan/5 border border-glow-cyan/20 text-[12px] text-white/65 leading-relaxed">
        <span className="text-glow-cyan font-semibold">Tip:</span> code against{' '}
        <CopyChip text='model="ollabridge:auto"' /> in any OpenAI SDK. OllaBridge resolves it
        to the best live route every time — no client changes when new models drop.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {allAliases.map(({ alias, candidates }) => (
          <AliasCard key={alias} alias={alias} candidates={candidates} />
        ))}
        {allAliases.length === 0 && (
          <div className="col-span-full px-3 py-6 text-center text-white/40 text-sm">
            No aliases loaded. Refresh the catalog from the Connect tab.
          </div>
        )}
      </div>
    </GlassCard>
  )
}

// ── Tab: Usage ──────────────────────────────────────────────────

function ProviderCard({ provider }: { provider: ProviderSummary }) {
  const queryClient = useQueryClient()
  const toggle = useMutation({
    mutationFn: () =>
      provider.enabled
        ? api.providersDisable(provider.id)
        : api.providersEnable(provider.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['providersList'] }),
  })

  const health = provider.state?.health ?? 'unknown'
  const color = HEALTH_COLORS[health] || '#64748b'

  return (
    <div
      className="px-4 py-3 rounded-xl border transition-colors"
      style={{
        background: `linear-gradient(135deg, ${color}08, ${color}03)`,
        borderColor: `${color}30`,
      }}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <Cpu size={16} style={{ color }} />
          <div className="min-w-0">
            <div className="text-white/90 text-sm font-semibold truncate">{provider.name}</div>
            <div className="text-[11px] text-white/40 font-mono truncate">{provider.id}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <HealthDot health={health} />
          <span className="text-[10px] uppercase tracking-wider font-semibold" style={{ color }}>
            {health.replace('_', ' ')}
          </span>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-2">
        <Stat label="Requests" value={provider.state?.request_count ?? 0} />
        <Stat
          label="Avg latency"
          value={provider.state ? `${provider.state.avg_latency_ms.toFixed(0)}ms` : '—'}
        />
        <Stat label="Failures" value={provider.state?.consecutive_failures ?? 0} />
      </div>
      <div className="flex items-center justify-between gap-2 mt-3">
        <div className="flex flex-wrap gap-1">
          {provider.tags.slice(0, 3).map((t) => (
            <span
              key={t}
              className="px-1.5 py-0.5 rounded text-[10px] text-white/45 bg-white/[0.04] border border-white/[0.06]"
            >
              {t}
            </span>
          ))}
        </div>
        <button
          onClick={() => toggle.mutate()}
          disabled={toggle.isPending}
          className="text-[11px] font-medium px-2 py-0.5 rounded-md transition-colors"
          style={{
            background: provider.enabled ? 'rgba(20,184,166,0.12)' : 'rgba(255,255,255,0.04)',
            color: provider.enabled ? '#14b8a6' : 'rgba(255,255,255,0.45)',
            border: `1px solid ${provider.enabled ? 'rgba(20,184,166,0.3)' : 'rgba(255,255,255,0.1)'}`,
          }}
        >
          {provider.enabled ? 'Enabled' : 'Disabled'}
        </button>
      </div>
      {provider.state?.last_error && (
        <div className="mt-2 text-[10px] text-red-300/80 truncate">
          ⚠ {provider.state.last_error}
        </div>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="px-2 py-1.5 rounded-md bg-navy-900/40">
      <div className="text-[9px] uppercase tracking-wider text-white/30 leading-none">{label}</div>
      <div className="text-white/85 text-sm font-semibold font-mono mt-0.5">{value}</div>
    </div>
  )
}

function UsageTab() {
  const { data, isLoading } = useProvidersList()
  const providers = data?.providers ?? []
  const enabled = providers.filter((p) => p.enabled)
  const totalRequests = providers.reduce((acc, p) => acc + (p.state?.request_count ?? 0), 0)
  const avgLatency =
    enabled
      .map((p) => p.state?.avg_latency_ms ?? 0)
      .filter((v) => v > 0)
      .reduce((a, b, _, arr) => a + b / arr.length, 0) || 0

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Providers" value={providers.length} sublabel={`${enabled.length} enabled`} color="#22d3ee" icon={Boxes} />
        <KPI
          label="Healthy"
          value={providers.filter((p) => p.state?.health === 'healthy').length}
          sublabel="live routes"
          color="#14b8a6"
          icon={CheckCircle2}
        />
        <KPI
          label="Requests"
          value={totalRequests}
          sublabel="since startup"
          color="#8b5cf6"
          icon={Activity}
        />
        <KPI
          label="Avg latency"
          value={`${avgLatency.toFixed(0)}ms`}
          sublabel="across enabled"
          color="#fbbf24"
          icon={Zap}
        />
      </div>

      <GlassCard>
        <SectionTitle
          icon={Activity}
          title="Provider fleet"
          subtitle="Live health, fail-overs, and quota state for every registered provider."
          color="#14b8a6"
        />
        {isLoading ? (
          <div className="text-center text-white/40 text-sm py-6">Loading…</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {providers.map((p) => (
              <ProviderCard key={p.id} provider={p} />
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  )
}

function KPI({
  label,
  value,
  sublabel,
  color,
  icon: Icon,
}: {
  label: string
  value: string | number
  sublabel?: string
  color: string
  icon: typeof Activity
}) {
  return (
    <GlassCard className="!p-4">
      <div className="flex items-center gap-2 mb-1.5">
        <Icon size={14} style={{ color }} />
        <div className="text-[10px] uppercase tracking-wider text-white/40 font-semibold">{label}</div>
      </div>
      <div className="text-white text-2xl font-bold font-mono">{value}</div>
      {sublabel && <div className="text-[11px] text-white/40 mt-0.5">{sublabel}</div>}
    </GlassCard>
  )
}

// ── Root ───────────────────────────────────────────────────────

export function ProvidersPage() {
  const [tab, setTab] = useState<Tab>('connect')

  return (
    <div className="relative h-full overflow-y-auto">
      {/* Soft ambient glow */}
      <div className="absolute -top-32 -right-32 w-[500px] h-[500px] bloom-violet pointer-events-none" />
      <div className="absolute top-1/3 -left-32 w-[400px] h-[400px] bloom-cyan pointer-events-none" />

      <div className="relative max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Page header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <div className="w-11 h-11 rounded-2xl flex items-center justify-center glow-cyan"
                style={{
                  background: 'linear-gradient(135deg, rgba(0,229,255,0.2), rgba(139,92,246,0.1))',
                  border: '1px solid rgba(0,229,255,0.3)',
                }}>
                <PlugZap size={20} className="text-glow-cyan" />
              </div>
              <h1 className="text-2xl font-bold text-white">Providers Hub</h1>
            </div>
            <p className="text-white/50 text-sm max-w-2xl leading-relaxed">
              One gateway for local Ollama, remote nodes, Hugging Face Inference Providers, and OllaBridge Cloud.
              Capability-routed: applications code against stable intent aliases while the underlying model rotates
              as the catalog refreshes.
            </p>
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
                    layoutId="providers-tab"
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

        {/* Tab body */}
        <div>
          {tab === 'connect' && <ConnectTab />}
          {tab === 'discover' && <DiscoverTab />}
          {tab === 'route' && <RouteTab />}
          {tab === 'usage' && <UsageTab />}
        </div>
      </div>
    </div>
  )
}
