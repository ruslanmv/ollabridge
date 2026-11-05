/** Settings → Rate limits: OllaBridge's own inbound limit, and per-provider
 * pacing, concurrency, retry and cooldown, with live state (requests running
 * and waiting, recent rate-limited answers, "cooling down until …"). */

import { useCallback, useEffect, useState, type ReactNode, type RefObject } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Check,
  Gauge,
  Loader2,
  Plus,
  RotateCcw,
  Save,
  Sparkles,
  X,
} from 'lucide-react'
import { api } from '../../lib/api'
import type {
  InboundLimit,
  ProviderLimit,
  ProviderRateRow,
  RateLimitSettings,
  RateLimitsResponse,
} from '../../lib/api'
import { useRateLimits } from '../../lib/hooks'
import { GlassCard, SectionTitle, SettingField, Toggle } from './ui'

const LIMIT_KEYS = [
  'requests_per_minute',
  'max_concurrent',
  'on_rate_limit',
  'max_wait_seconds',
  'cooldown_seconds',
] as const

// Mirrors BASE_BACKOFF_SECONDS in addons/providers/pacing.py.
const BASE_BACKOFF_SECONDS = 5

function sameLimit(a: ProviderLimit, b: ProviderLimit): boolean {
  return LIMIT_KEYS.every((k) => a[k] === b[k])
}

/** The settings as the gateway stores them: entries equal to the defaults dropped. */
function pruned(s: RateLimitSettings, defaults: ProviderLimit): RateLimitSettings {
  const providers: Record<string, ProviderLimit> = {}
  for (const [id, limit] of Object.entries(s.providers)) {
    if (!sameLimit(limit, defaults)) providers[id] = limit
  }
  return { inbound: s.inbound, providers }
}

function canon(s: RateLimitSettings, defaults: ProviderLimit): string {
  const p = pruned(s, defaults)
  return JSON.stringify({
    inbound: [p.inbound.enabled, p.inbound.requests_per_minute],
    providers: Object.keys(p.providers)
      .sort()
      .map((id) => [id, ...LIMIT_KEYS.map((k) => p.providers[id][k])]),
  })
}

function timeOf(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleTimeString() : ''
}

function seconds(n: number): string {
  return `${Number.isInteger(n) ? n : n.toFixed(1)} s`
}

/** The limits in words, so the numbers read as behaviour. */
function describe(l: ProviderLimit): string {
  const pace =
    l.requests_per_minute > 0
      ? `Calls start at most once every ${seconds(60 / l.requests_per_minute)}`
      : 'Calls are not paced'
  const cap = l.max_concurrent > 0 ? `, ${l.max_concurrent} at a time` : ''
  let onLimit: string
  if (l.on_rate_limit === 'wait_retry') {
    const first = l.cooldown_seconds || BASE_BACKOFF_SECONDS
    onLimit =
      `A rate limit is retried after ${seconds(first)}, then doubling (a longer Retry-After wins), ` +
      `for up to ${seconds(l.max_wait_seconds)} per call; other calls wait meanwhile.`
  } else if (l.cooldown_seconds > 0) {
    onLimit =
      `A rate limit is answered with a 429 at once, and for ${seconds(l.cooldown_seconds)} after it ` +
      'calls get a 429 without reaching the provider.'
  } else {
    onLimit = 'A rate limit is answered with a 429 at once (as before).'
  }
  return `${pace}${cap}. ${onLimit}`
}

function NumberInput({
  value,
  onChange,
  min = 0,
  max,
}: {
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
}) {
  return (
    <input
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      value={value}
      onChange={(e) => {
        const n = Math.floor(Number(e.target.value))
        onChange(Number.isFinite(n) ? n : 0)
      }}
      className="w-28 px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-sm text-white/80 font-mono focus:outline-none focus:border-glow-cyan/40 transition-colors"
    />
  )
}

function LimitField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs text-white/60 font-medium">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-white/30">{hint}</span>}
    </label>
  )
}

function Chip({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span
      className="px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{ background: `${color}15`, color, border: `1px solid ${color}30` }}
    >
      {children}
    </span>
  )
}

function SmallButton({
  onClick,
  icon: Icon,
  children,
  title,
}: {
  onClick: () => void
  icon: typeof Plus
  children?: ReactNode
  title?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-white/50 hover:text-white/80 hover:bg-white/5 border border-white/[0.06] transition-colors"
    >
      <Icon size={12} />
      {children}
    </button>
  )
}

function ProviderCard({
  row,
  limit,
  defaults,
  suggested,
  onChange,
  onHide,
}: {
  row: ProviderRateRow
  limit: ProviderLimit
  defaults: ProviderLimit
  suggested: ProviderLimit
  onChange: (limit: ProviderLimit) => void
  onHide?: () => void
}) {
  const s = row.state
  const set = (patch: Partial<ProviderLimit>) => onChange({ ...limit, ...patch })
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-white/85 font-medium">{row.name}</span>
        <code className="text-[11px] text-white/35">{row.id}</code>
        {!row.registered && <Chip color="#94a3b8">not registered right now</Chip>}
        {s.cooling_down_until && s.cooldown_remaining_s > 0 && (
          <Chip color="#f59e0b">cooling down until {timeOf(s.cooling_down_until)}</Chip>
        )}
        {(s.in_flight > 0 || s.waiting > 0) && (
          <Chip color="#00e5ff">
            {s.in_flight} running · {s.waiting} waiting
          </Chip>
        )}
        {s.rate_limited_last_hour > 0 && (
          <Chip color="#f87171">
            {s.rate_limited_last_hour} rate limit{s.rate_limited_last_hour === 1 ? '' : 's'} in the last hour
          </Chip>
        )}
        <div className="ml-auto flex items-center gap-1">
          {!sameLimit(limit, suggested) && (
            <SmallButton
              onClick={() => onChange(suggested)}
              icon={Sparkles}
              title="A cautious starting point for a provider whose limit is not published"
            >
              Use suggested
            </SmallButton>
          )}
          {!sameLimit(limit, defaults) && (
            <SmallButton onClick={() => onChange(defaults)} icon={RotateCcw} title="No limits, fail fast">
              Defaults
            </SmallButton>
          )}
          {onHide && <SmallButton onClick={onHide} icon={X} title="Hide this provider" />}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <LimitField label="Requests / minute" hint="0 = no pacing">
          <NumberInput value={limit.requests_per_minute} max={10000} onChange={(v) => set({ requests_per_minute: v })} />
        </LimitField>
        <LimitField label="Max concurrent" hint="0 = no cap">
          <NumberInput value={limit.max_concurrent} max={1000} onChange={(v) => set({ max_concurrent: v })} />
        </LimitField>
        <LimitField label="On a rate limit">
          <select
            value={limit.on_rate_limit}
            onChange={(e) => set({ on_rate_limit: e.target.value as ProviderLimit['on_rate_limit'] })}
            className="w-36 px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-sm text-white/80 focus:outline-none focus:border-glow-cyan/40 transition-colors appearance-none cursor-pointer"
          >
            <option value="fail_fast" className="bg-navy-800">Fail fast</option>
            <option value="wait_retry" className="bg-navy-800">Wait and retry</option>
          </select>
        </LimitField>
        <LimitField label="Max wait (s)" hint="queue + retries, per call">
          <NumberInput value={limit.max_wait_seconds} min={1} max={3600} onChange={(v) => set({ max_wait_seconds: v })} />
        </LimitField>
        <LimitField label="Cooldown (s)" hint="after a rate limit; 0 = none">
          <NumberInput value={limit.cooldown_seconds} max={3600} onChange={(v) => set({ cooldown_seconds: v })} />
        </LimitField>
      </div>

      <p className="text-xs text-white/40">{describe(limit)}</p>

      {(s.retries > 0 || s.refused_in_cooldown > 0 || s.refused_queue_full > 0) && (
        <p className="text-[11px] text-white/35">
          Since start: {s.retries} retried, {s.recovered} recovered after retrying, {s.refused_in_cooldown} refused
          during a cooldown, {s.refused_queue_full} refused for waiting longer than the max wait.
        </p>
      )}

      {s.recent.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] uppercase tracking-wider text-white/30">Recent rate-limited answers</div>
          {s.recent.slice(0, 5).map((e, i) => (
            <div key={`${e.at}-${i}`} className="flex flex-wrap items-baseline gap-x-3 text-xs">
              <span className="font-mono text-white/45">{timeOf(e.at)}</span>
              <span className="text-white/35">{e.status ? `HTTP ${e.status}` : '—'}</span>
              <span className="text-amber-300/80">{e.outcome}</span>
              <span className="text-white/30 truncate max-w-full" title={e.message}>
                {e.message}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function RateLimitsSection({
  delay = 0,
  saveRef,
}: {
  delay?: number
  /** Set to this section's save while it has unsaved changes, else null. */
  saveRef?: RefObject<(() => Promise<void>) | null>
}) {
  const { data, isLoading, error } = useRateLimits()
  const queryClient = useQueryClient()
  // null = follow what the gateway has; set once the user edits something.
  const [draft, setDraft] = useState<RateLimitSettings | null>(null)
  const [added, setAdded] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const current = draft ?? data?.settings ?? null
  const dirty =
    !!data && !!draft && canon(draft, data.defaults.provider) !== canon(data.settings, data.defaults.provider)

  const save = useCallback(async () => {
    if (!data || !draft) return
    setSaving(true)
    setSaveError(null)
    try {
      const res = await api.updateRateLimits(pruned(draft, data.defaults.provider))
      queryClient.setQueryData<RateLimitsResponse>(['rateLimits'], res)
      setDraft(null)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Failed to save rate limits')
      throw e
    } finally {
      setSaving(false)
    }
  }, [data, draft, queryClient])

  useEffect(() => {
    if (!saveRef) return
    saveRef.current = dirty ? save : null
    return () => {
      saveRef.current = null
    }
  }, [saveRef, dirty, save])

  const header = (
    <SectionTitle
      icon={Gauge}
      title="Rate limits"
      subtitle="Pace calls to providers that rate-limit you, and cap OllaBridge's own clients"
      color="#a78bfa"
      badge={
        data?.providers.some((p) => p.state.cooldown_remaining_s > 0)
          ? { label: 'Cooling down', color: '#f59e0b' }
          : data && (data.settings.inbound.enabled || Object.keys(data.settings.providers).length > 0)
            ? { label: 'Active', color: '#a78bfa' }
            : undefined
      }
    />
  )

  if (!data || !current) {
    const message = error instanceof Error ? error.message : ''
    return (
      <GlassCard delay={delay}>
        {header}
        {isLoading ? (
          <div className="flex items-center gap-2 text-white/40 text-sm">
            <Loader2 size={16} className="animate-spin" />
            Loading rate limits…
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-amber-300/80">
            <AlertTriangle size={14} />
            {message.includes(': 404')
              ? 'This gateway was started before rate limits existed. Restart OllaBridge to use this section.'
              : `Could not load rate limits${message ? ` (${message})` : ''}.`}
          </div>
        )}
      </GlassCard>
    )
  }

  const defaults = data.defaults.provider
  const edit = (next: RateLimitSettings) => setDraft(next)
  const setInbound = (patch: Partial<InboundLimit>) =>
    edit({ ...current, inbound: { ...current.inbound, ...patch } })
  const limitOf = (id: string) => current.providers[id] ?? defaults
  const setProvider = (id: string, limit: ProviderLimit) =>
    edit({ ...current, providers: { ...current.providers, [id]: limit } })

  // Providers that are limited, in use, or were just rate limited; any other
  // can be added from the list.
  const isShown = (r: ProviderRateRow) =>
    r.configured ||
    r.requests > 0 ||
    r.state.recent.length > 0 ||
    r.state.in_flight > 0 ||
    r.state.waiting > 0 ||
    r.id in current.providers ||
    added.includes(r.id)
  const shown = data.providers.filter(isShown)
  const addable = data.providers.filter((r) => !isShown(r) && r.enabled)
  const inbound = data.inbound

  return (
    <GlassCard delay={delay}>
      {header}

      {/* OllaBridge's own limit */}
      <div className="space-y-0">
        <SettingField
          label="Limit incoming model calls"
          description="OllaBridge's own limit, per client address and API key. Counts POST /v1/… only; the dashboard is never limited. Off keeps today's behaviour."
        >
          <Toggle enabled={current.inbound.enabled} onToggle={() => setInbound({ enabled: !current.inbound.enabled })} />
        </SettingField>
        {current.inbound.enabled && (
          <SettingField
            label="Requests per minute"
            description="Per client; past it a call gets HTTP 429 with Retry-After"
          >
            <NumberInput
              value={current.inbound.requests_per_minute}
              min={1}
              max={100000}
              onChange={(v) => setInbound({ requests_per_minute: v })}
            />
          </SettingField>
        )}
        {(inbound.enabled || inbound.refused_last_hour > 0) && (
          <div className="py-2 text-xs text-white/35 space-y-1">
            <div>
              {inbound.active_clients} client{inbound.active_clients === 1 ? '' : 's'} active this minute ·{' '}
              {inbound.refused_last_hour} call{inbound.refused_last_hour === 1 ? '' : 's'} refused in the last hour
            </div>
            {inbound.recent.slice(0, 3).map((r, i) => (
              <div key={`${r.at}-${i}`} className="flex gap-3">
                <span className="font-mono text-white/45">{timeOf(r.at)}</span>
                <span>{r.client}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Providers */}
      <div className="mt-5 pt-5 border-t border-white/[0.04] space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-sm text-white/70 font-medium">Providers</div>
            <p className="text-xs text-white/30 mt-0.5">
              Calls to a provider wait their turn instead of tripping its limit. A provider left at the
              defaults is not limited and fails fast, as before.
            </p>
          </div>
          {addable.length > 0 && (
            <div className="flex items-center gap-1.5">
              <Plus size={14} className="text-white/30" />
              <select
                value=""
                onChange={(e) => e.target.value && setAdded([...added, e.target.value])}
                className="px-3 py-1.5 rounded-xl bg-white/5 border border-white/10 text-xs text-white/70 focus:outline-none cursor-pointer"
              >
                <option value="" className="bg-navy-800">
                  Add a provider…
                </option>
                {addable.map((r) => (
                  <option key={r.id} value={r.id} className="bg-navy-800">
                    {r.name} ({r.id})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {shown.length === 0 && (
          <p className="text-xs text-white/30">
            No provider has been used or limited yet. Add one from the list above.
          </p>
        )}
        {shown.map((row) => (
          <ProviderCard
            key={row.id}
            row={row}
            limit={limitOf(row.id)}
            defaults={defaults}
            suggested={data.defaults.suggested}
            onChange={(limit) => setProvider(row.id, limit)}
            onHide={
              added.includes(row.id) && !row.configured
                ? () => {
                    setAdded(added.filter((id) => id !== row.id))
                    const providers = { ...current.providers }
                    delete providers[row.id]
                    edit({ ...current, providers })
                  }
                : undefined
            }
          />
        ))}
      </div>

      {/* Save */}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
        {saveError ? (
          <span className="flex items-center gap-1.5 text-xs text-red-400">
            <AlertTriangle size={13} />
            {saveError}
          </span>
        ) : (
          <span className="text-xs text-white/30">
            {dirty ? 'Unsaved changes.' : 'Saved in the gateway.'} Changes apply at once; no restart.
          </span>
        )}
        <button
          type="button"
          onClick={() => save().catch(() => undefined)}
          disabled={!dirty || saving}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 disabled:opacity-40"
          style={{
            background: saved
              ? 'linear-gradient(135deg, rgba(20,184,166,0.3), rgba(20,184,166,0.15))'
              : 'linear-gradient(135deg, rgba(167,139,250,0.22), rgba(0,229,255,0.15))',
            border: saved ? '1px solid rgba(20,184,166,0.4)' : '1px solid rgba(167,139,250,0.35)',
            color: saved ? '#14b8a6' : '#c4b5fd',
          }}
        >
          {saving ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              Saving…
            </>
          ) : saved ? (
            <>
              <Check size={14} />
              Saved
            </>
          ) : (
            <>
              <Save size={14} />
              Save rate limits
            </>
          )}
        </button>
      </div>
    </GlassCard>
  )
}
