/**
 * One model download, animated: a progress ring with orbiting sparks, a
 * shimmering bar, live speed and time left, and a small celebration when the
 * model is installed. Polls /local/models/pull/<ref> until it ends.
 */
import { motion, useReducedMotion } from 'framer-motion'
import { AlertTriangle, Check, Copy, RotateCcw, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useCancelLocalPull, usePullStatus, useStartLocalPull } from '../../lib/localHooks'
import { formatBytes } from './modelRefs'

const CYAN = '#00e5ff'
const VIOLET = '#8b5cf6'
const GREEN = '#34d399'
const RED = '#f87171'

const RING = 2 * Math.PI * 22 // circumference of the r=22 progress ring

function formatEta(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return ''
  if (seconds < 60) return 'less than a minute left'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min left`
  return `${(seconds / 3600).toFixed(1)} h left`
}

function phaseLabel(status: string, detail: string | null | undefined, hasTotal: boolean): string {
  if (status === 'queued') return 'Waiting for the download before it'
  if (status === 'completed') return 'Installed · ready to use'
  const d = (detail || '').toLowerCase()
  if (d.startsWith('verifying')) return 'Verifying the files'
  if (d.startsWith('writing') || d.startsWith('removing')) return 'Finishing up'
  return hasTotal ? 'Downloading' : 'Preparing'
}

export function DownloadCard({
  modelRef,
  onInstalled,
  onDismiss,
}: {
  modelRef: string
  onInstalled: () => void
  onDismiss: () => void
}) {
  const still = useReducedMotion()
  const queryClient = useQueryClient()
  const { data, error: lookupError } = usePullStatus(modelRef)
  const cancel = useCancelLocalPull()
  const restart = useStartLocalPull()
  const [copied, setCopied] = useState(false)

  // Download speed, smoothed over the last few samples.
  const sample = useRef<{ bytes: number; at: number } | null>(null)
  const [speed, setSpeed] = useState(0)
  const completedBytes = data?.completed_bytes ?? 0
  useEffect(() => {
    const now = Date.now()
    const last = sample.current
    if (last && completedBytes > last.bytes && now > last.at) {
      const current = ((completedBytes - last.bytes) / (now - last.at)) * 1000
      setSpeed((previous) => (previous ? previous * 0.7 + current * 0.3 : current))
    }
    if (!last || completedBytes !== last.bytes) sample.current = { bytes: completedBytes, at: now }
  }, [completedBytes])

  const status = data?.status ?? (lookupError ? 'error' : 'queued')
  const done = status === 'completed'
  const failed = status === 'error'
  const cancelled = failed && data?.error === 'cancelled'
  const running = status === 'running'

  // Tell the page once, so the new model shows up in the inventory.
  const announced = useRef(false)
  useEffect(() => {
    if (done && !announced.current) {
      announced.current = true
      onInstalled()
    }
  }, [done, onInstalled])

  const total = data?.total_bytes ?? 0
  const percent = done ? 100 : Math.min(99.9, data?.progress_pct ?? 0)
  const accent = done ? GREEN : failed ? RED : CYAN
  const remaining = running && speed > 0 && total > completedBytes ? (total - completedBytes) / speed : 0

  const failure = cancelled
    ? 'Cancelled. What was downloaded is kept, so it resumes from here.'
    : data?.error || (lookupError ? 'This download is no longer running.' : '')

  const retry = () => {
    announced.current = false
    sample.current = null
    setSpeed(0)
    restart.mutate(
      { model: modelRef },
      { onSuccess: () => queryClient.invalidateQueries({ queryKey: ['local', 'pull', modelRef] }) },
    )
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(modelRef)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable: nothing to do
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.97 }}
      className="relative overflow-hidden rounded-2xl px-4 py-3.5"
      style={{
        background: 'linear-gradient(135deg, rgba(15,22,60,0.85), rgba(8,12,35,0.8))',
        border: `1px solid ${accent}33`,
        boxShadow: running ? `0 0 28px ${CYAN}14` : undefined,
      }}
    >
      {/* A slow aurora behind the card while bytes are moving */}
      {running && !still && (
        <motion.div
          aria-hidden
          className="pointer-events-none absolute -inset-10 opacity-40"
          style={{
            background: `radial-gradient(40% 60% at 20% 50%, ${CYAN}22, transparent 70%), radial-gradient(40% 60% at 80% 50%, ${VIOLET}22, transparent 70%)`,
          }}
          animate={{ x: [-20, 20, -20] }}
          transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}

      <div className="relative flex items-center gap-4">
        <ProgressRing percent={percent} accent={accent} state={done ? 'done' : failed ? 'failed' : running ? 'running' : 'waiting'} still={!!still} />

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate font-mono text-sm font-medium text-white/85" title={modelRef}>
              {modelRef}
            </p>
            {done && (
              <button
                onClick={copy}
                className="shrink-0 text-white/30 transition-colors hover:text-white/70"
                title="Copy the model id"
                aria-label="Copy the model id"
              >
                {copied ? <Check size={13} style={{ color: GREEN }} /> : <Copy size={13} />}
              </button>
            )}
          </div>

          <p className="mt-0.5 text-xs" style={{ color: failed ? RED : done ? GREEN : 'rgba(255,255,255,0.45)' }}>
            {failed ? failure : phaseLabel(status, data?.detail, total > 0)}
          </p>

          {!failed && (
            <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
              <motion.div
                className="relative h-full rounded-full"
                style={{ background: done ? GREEN : `linear-gradient(90deg, ${CYAN}, ${VIOLET})` }}
                initial={false}
                animate={{ width: `${total > 0 || done ? percent : 0}%` }}
                transition={{ type: 'spring', stiffness: 60, damping: 18 }}
              >
                {running && !still && (
                  <motion.span
                    aria-hidden
                    className="absolute inset-y-0 w-16"
                    style={{ background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.55), transparent)' }}
                    animate={{ left: ['-30%', '110%'] }}
                    transition={{ duration: 1.4, repeat: Infinity, ease: 'linear' }}
                  />
                )}
              </motion.div>
              {/* Nothing to measure yet: a bar that sweeps instead of sitting empty */}
              {running && total === 0 && !still && (
                <motion.div
                  aria-hidden
                  className="-mt-1.5 h-1.5 w-1/3 rounded-full"
                  style={{ background: `linear-gradient(90deg, transparent, ${CYAN}, transparent)` }}
                  animate={{ x: ['-100%', '300%'] }}
                  transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
                />
              )}
            </div>
          )}

          {!failed && !done && total > 0 && (
            <p className="mt-1.5 text-[11px] tabular-nums text-white/35">
              {formatBytes(completedBytes)} of {formatBytes(total)}
              {speed > 0 && ` · ${formatBytes(speed)}/s`}
              {remaining > 0 && ` · ${formatEta(remaining)}`}
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {(running || status === 'queued') && (
            <button
              onClick={() => cancel.mutate({ model: modelRef })}
              disabled={cancel.isPending}
              className="rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-white/45 transition-colors hover:border-white/25 hover:text-white/80"
            >
              Cancel
            </button>
          )}
          {failed && (
            <button
              onClick={retry}
              disabled={restart.isPending}
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium"
              style={{ background: `${CYAN}14`, border: `1px solid ${CYAN}33`, color: CYAN }}
            >
              <RotateCcw size={12} />
              {cancelled ? 'Resume' : 'Retry'}
            </button>
          )}
          {(done || failed) && (
            <button
              onClick={onDismiss}
              className="rounded-lg p-1.5 text-white/30 transition-colors hover:text-white/70"
              aria-label="Dismiss"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>
    </motion.div>
  )
}

function ProgressRing({
  percent,
  accent,
  state,
  still,
}: {
  percent: number
  accent: string
  state: 'waiting' | 'running' | 'done' | 'failed'
  still: boolean
}) {
  return (
    <div className="relative h-14 w-14 shrink-0">
      {/* Sparks circling the ring while it downloads */}
      {state === 'running' && !still && (
        <motion.div
          aria-hidden
          className="absolute inset-0"
          animate={{ rotate: 360 }}
          transition={{ duration: 2.6, repeat: Infinity, ease: 'linear' }}
        >
          <span
            className="absolute left-1/2 top-0 h-1.5 w-1.5 -translate-x-1/2 rounded-full"
            style={{ background: CYAN, boxShadow: `0 0 10px ${CYAN}` }}
          />
          <span
            className="absolute bottom-0 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full"
            style={{ background: VIOLET, boxShadow: `0 0 8px ${VIOLET}` }}
          />
        </motion.div>
      )}

      {/* The celebration: sparks flying out once, when the model is installed */}
      {state === 'done' &&
        !still &&
        Array.from({ length: 10 }, (_, i) => {
          const angle = (i / 10) * 2 * Math.PI
          return (
            <motion.span
              key={i}
              aria-hidden
              className="absolute left-1/2 top-1/2 h-1 w-1 rounded-full"
              style={{ background: i % 2 ? GREEN : CYAN }}
              initial={{ x: 0, y: 0, opacity: 1, scale: 1 }}
              animate={{ x: Math.cos(angle) * 38, y: Math.sin(angle) * 38, opacity: 0, scale: 0.4 }}
              transition={{ duration: 0.9, ease: 'easeOut' }}
            />
          )
        })}

      <svg viewBox="0 0 56 56" className="absolute inset-0 -rotate-90">
        <circle cx="28" cy="28" r="22" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="4" />
        <motion.circle
          cx="28"
          cy="28"
          r="22"
          fill="none"
          stroke={accent}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={RING}
          initial={false}
          animate={{ strokeDashoffset: RING * (1 - percent / 100) }}
          transition={{ type: 'spring', stiffness: 60, damping: 18 }}
          style={{ filter: `drop-shadow(0 0 6px ${accent}aa)` }}
        />
      </svg>

      <div className="absolute inset-0 flex items-center justify-center">
        {state === 'done' ? (
          <motion.svg viewBox="0 0 24 24" className="h-6 w-6" initial={still ? false : { scale: 0.4 }} animate={{ scale: 1 }}>
            <motion.path
              d="M5 12.5l4.5 4.5L19 7.5"
              fill="none"
              stroke={GREEN}
              strokeWidth="2.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={still ? false : { pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.45, ease: 'easeOut' }}
            />
          </motion.svg>
        ) : state === 'failed' ? (
          <AlertTriangle size={18} style={{ color: RED }} />
        ) : (
          <span className="text-[11px] font-semibold tabular-nums text-white/80">{Math.floor(percent)}%</span>
        )}
      </div>
    </div>
  )
}
