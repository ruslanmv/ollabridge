import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Cloud,
  Wifi,
  WifiOff,
  Link2,
  Unlink,
  RefreshCw,
  Copy,
  Check,
  AlertTriangle,
  Globe,
  Cpu,
  Timer,
  Loader2,
  Zap,
  ArrowRight,
  ShieldCheck,
} from 'lucide-react'
import { useCloudStatus } from '../../lib/hooks'
import { api, type CloudStatus } from '../../lib/api'
import { useMutation, useQueryClient } from '@tanstack/react-query'

// ── Helpers ─────────────────────────────────────────────────────────

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
  icon: typeof Cloud
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
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <h2 className="text-white/90 font-semibold text-base">{title}</h2>
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
        {subtitle && (
          <p className="text-white/40 text-xs mt-0.5">{subtitle}</p>
        )}
      </div>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [text])

  return (
    <motion.button
      onClick={handleCopy}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
      style={{
        background: copied ? 'rgba(20,184,166,0.15)' : 'rgba(255,255,255,0.05)',
        border: copied ? '1px solid rgba(20,184,166,0.3)' : '1px solid rgba(255,255,255,0.1)',
        color: copied ? '#14b8a6' : 'rgba(255,255,255,0.6)',
      }}
      whileTap={{ scale: 0.95 }}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {copied ? 'Copied' : 'Copy'}
    </motion.button>
  )
}

const STATE_COLORS: Record<string, string> = {
  disconnected: '#6b7280',
  pairing: '#f59e0b',
  connecting: '#3b82f6',
  connected: '#14b8a6',
  reconnecting: '#f59e0b',
  error: '#ef4444',
}

const STATE_LABELS: Record<string, string> = {
  disconnected: 'Disconnected',
  pairing: 'Pairing...',
  connecting: 'Connecting...',
  connected: 'Connected',
  reconnecting: 'Reconnecting...',
  error: 'Error',
}

function StatusDot({ state }: { state: string }) {
  const color = STATE_COLORS[state] || '#6b7280'
  const isActive = state === 'connected'
  return (
    <div className="relative">
      <div
        className="w-3 h-3 rounded-full"
        style={{ background: color }}
      />
      {isActive && (
        <div
          className="absolute inset-0 w-3 h-3 rounded-full animate-ping"
          style={{ background: color, opacity: 0.4 }}
        />
      )}
    </div>
  )
}

// ── Connection Status Card ──────────────────────────────────────────

function ConnectionStatusCard({ status }: { status: CloudStatus }) {
  const queryClient = useQueryClient()

  const disconnectMutation = useMutation({
    mutationFn: () => api.cloudDisconnect(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cloudStatus'] }),
  })

  const unlinkMutation = useMutation({
    mutationFn: () => api.cloudUnlink(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cloudStatus'] }),
  })

  const color = STATE_COLORS[status.state] || '#6b7280'

  return (
    <div className="space-y-5">
      {/* Status header */}
      <div
        className="flex items-center gap-4 px-5 py-4 rounded-xl"
        style={{
          background: `linear-gradient(135deg, ${color}10, ${color}05)`,
          border: `1px solid ${color}25`,
        }}
      >
        <StatusDot state={status.state} />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium" style={{ color }}>
              {STATE_LABELS[status.state]}
            </span>
            {status.reconnect_attempt > 0 && (
              <span className="text-xs text-white/30">
                (attempt {status.reconnect_attempt})
              </span>
            )}
          </div>
          {status.cloud_url && (
            <p className="text-xs text-white/40 font-mono mt-0.5 truncate">
              {status.cloud_url}
            </p>
          )}
        </div>
        {status.state === 'connected' && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => disconnectMutation.mutate()}
              disabled={disconnectMutation.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors bg-white/5 border border-white/10 text-white/50 hover:text-white/70 hover:border-white/20"
            >
              <WifiOff size={12} />
              Disconnect
            </button>
          </div>
        )}
      </div>

      {/* Stats grid (only when connected) */}
      {status.state === 'connected' && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            {
              icon: Cpu,
              label: 'Models Shared',
              value: String(status.models_count),
              color: '#8b5cf6',
            },
            {
              icon: Globe,
              label: 'Device ID',
              value: status.device_id || 'N/A',
              color: '#00e5ff',
            },
            {
              icon: Timer,
              label: 'Uptime',
              value: status.uptime_seconds
                ? `${Math.floor(status.uptime_seconds / 60)}m ${status.uptime_seconds % 60}s`
                : '0s',
              color: '#14b8a6',
            },
            {
              icon: Zap,
              label: 'Status',
              value: 'Live',
              color: '#14b8a6',
            },
          ].map((stat) => {
            const SIcon = stat.icon
            return (
              <div
                key={stat.label}
                className="px-4 py-3 rounded-xl bg-white/[0.02] border border-white/[0.06]"
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <SIcon size={12} style={{ color: stat.color }} />
                  <span className="text-[10px] text-white/35 uppercase tracking-wider">
                    {stat.label}
                  </span>
                </div>
                <p className="text-sm font-mono text-white/70 truncate">{stat.value}</p>
              </div>
            )
          })}
        </div>
      )}

      {/* Models list (when connected) */}
      {status.state === 'connected' && status.models_shared.length > 0 && (
        <div>
          <p className="text-[10px] text-white/35 uppercase tracking-wider mb-2">
            Models Available to Quest VR
          </p>
          <div className="flex flex-wrap gap-1.5">
            {status.models_shared.map((m) => (
              <span
                key={m}
                className="px-2.5 py-1 rounded-lg text-[11px] font-mono text-white/50 cursor-pointer hover:text-white/70 transition-colors"
                style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(255,255,255,0.08)',
                }}
                onClick={() => navigator.clipboard.writeText(m)}
                title={`Click to copy: ${m}`}
              >
                {m}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Error display */}
      {status.last_error && (
        <div className="flex items-start gap-2 px-4 py-3 rounded-xl bg-red-500/5 border border-red-500/15">
          <AlertTriangle size={14} className="text-red-400 shrink-0 mt-0.5" />
          <p className="text-xs text-red-400/80">{status.last_error}</p>
        </div>
      )}

      {/* Unlink button (when has credentials) */}
      {(status.device_id || status.cloud_url) && status.state !== 'pairing' && (
        <div className="pt-2 border-t border-white/[0.04]">
          <button
            onClick={() => {
              if (confirm('Unlink this PC from OllaBridge Cloud? This deletes saved credentials.')) {
                unlinkMutation.mutate()
              }
            }}
            disabled={unlinkMutation.isPending}
            className="flex items-center gap-1.5 text-xs text-white/25 hover:text-red-400 transition-colors"
          >
            <Unlink size={12} />
            Unlink from Cloud
          </button>
        </div>
      )}
    </div>
  )
}

// ── Pairing Flow ────────────────────────────────────────────────────

function PairingSection({ status }: { status: CloudStatus }) {
  const queryClient = useQueryClient()
  const [cloudUrl, setCloudUrl] = useState('https://ruslanmv-ollabridge.hf.space')
  const [pairingCode, setPairingCode] = useState('')
  const [expiresAt, setExpiresAt] = useState(0)
  const [verificationUrl, setVerificationUrl] = useState('')
  const [remaining, setRemaining] = useState(0)

  // Use server pairing state if active
  useEffect(() => {
    if (status.pairing_code) {
      setPairingCode(status.pairing_code)
      setExpiresAt(status.pairing_expires_at)
    }
  }, [status.pairing_code, status.pairing_expires_at])

  // Countdown timer
  useEffect(() => {
    if (!expiresAt) return
    const update = () => {
      const left = Math.max(0, expiresAt - Date.now() / 1000)
      setRemaining(Math.ceil(left))
      if (left <= 0) {
        setPairingCode('')
        setExpiresAt(0)
      }
    }
    update()
    const iv = setInterval(update, 1000)
    return () => clearInterval(iv)
  }, [expiresAt])

  const startMutation = useMutation({
    mutationFn: () => api.cloudPairStart(cloudUrl),
    onSuccess: (data) => {
      setPairingCode(data.user_code)
      setExpiresAt(Date.now() / 1000 + data.expires_in)
      setVerificationUrl(data.verification_url)
      queryClient.invalidateQueries({ queryKey: ['cloudStatus'] })
    },
  })

  const pollMutation = useMutation({
    mutationFn: () => api.cloudPairPoll(),
    onSuccess: (data) => {
      if (data.status === 'approved') {
        setPairingCode('')
        setExpiresAt(0)
        queryClient.invalidateQueries({ queryKey: ['cloudStatus'] })
      }
    },
  })

  // Auto-poll while pairing
  useEffect(() => {
    if (status.state !== 'pairing' || !pairingCode) return
    const iv = setInterval(() => pollMutation.mutate(), 3000)
    return () => clearInterval(iv)
  }, [status.state, pairingCode])

  const isAlreadyLinked = status.state === 'connected' || status.device_id

  if (isAlreadyLinked) return null

  return (
    <div className="space-y-5">
      {/* Cloud URL input */}
      {!pairingCode && (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-white/40 uppercase tracking-wider block mb-1.5">
              OllaBridge Cloud URL
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={cloudUrl}
                onChange={(e) => setCloudUrl(e.target.value)}
                placeholder="https://your-cloud-instance.example.com"
                className="flex-1 px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-sm text-white/80 font-mono placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
              />
              <motion.button
                onClick={() => startMutation.mutate()}
                disabled={startMutation.isPending || !cloudUrl.trim()}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all disabled:opacity-50"
                style={{
                  background: 'linear-gradient(135deg, rgba(0,229,255,0.2), rgba(139,92,246,0.15))',
                  border: '1px solid rgba(0,229,255,0.3)',
                  color: '#00e5ff',
                }}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                {startMutation.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Link2 size={14} />
                )}
                Link to Cloud
              </motion.button>
            </div>
          </div>

          {startMutation.isError && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/5 border border-red-500/15">
              <AlertTriangle size={12} className="text-red-400" />
              <span className="text-xs text-red-400/80">
                {startMutation.error instanceof Error ? startMutation.error.message : 'Failed to start pairing'}
              </span>
            </div>
          )}

          <p className="text-xs text-white/30">
            Enter the URL of your OllaBridge Cloud instance. A pairing code will be displayed
            that you confirm on the Cloud dashboard to authorize this PC.
          </p>
        </div>
      )}

      {/* Pairing code display */}
      <AnimatePresence>
        {pairingCode && (
          <motion.div
            className="rounded-2xl overflow-hidden"
            style={{
              background: 'linear-gradient(135deg, rgba(0,229,255,0.08), rgba(139,92,246,0.05))',
              border: '1px solid rgba(0,229,255,0.2)',
            }}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
          >
            <div className="px-6 py-6 text-center">
              <p className="text-xs text-white/40 uppercase tracking-wider mb-3">
                Enter this code on OllaBridge Cloud
              </p>

              <div className="flex items-center justify-center gap-4 mb-3">
                <code
                  className="text-5xl font-mono font-bold tracking-[0.5em] select-all"
                  style={{ color: '#00e5ff', textShadow: '0 0 30px rgba(0,229,255,0.4)' }}
                >
                  {pairingCode}
                </code>
              </div>

              <div className="flex items-center justify-center gap-4 mb-4">
                <CopyButton text={pairingCode.replace('-', '')} />
                <div className="flex items-center gap-1.5">
                  <Timer size={12} className="text-white/30" />
                  <span className="text-xs text-white/40">{remaining}s remaining</span>
                </div>
              </div>

              {verificationUrl && (
                <a
                  href={verificationUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs text-glow-cyan/70 hover:text-glow-cyan transition-colors"
                >
                  <Globe size={12} />
                  Open Cloud Dashboard to confirm
                  <ArrowRight size={10} />
                </a>
              )}

              <div className="mt-4 flex items-center justify-center gap-2 text-xs text-white/25">
                <Loader2 size={12} className="animate-spin" />
                Waiting for confirmation...
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── How It Works ────────────────────────────────────────────────────

function HowItWorks() {
  const steps = [
    {
      icon: Link2,
      title: 'Pair Your PC',
      desc: 'Click "Link to Cloud" to generate a pairing code. Confirm the code on the OllaBridge Cloud dashboard.',
      color: '#00e5ff',
    },
    {
      icon: Wifi,
      title: 'Auto-Connect',
      desc: 'Your PC opens a secure WebSocket tunnel to the cloud. Models from Ollama and HomePilot are registered automatically.',
      color: '#8b5cf6',
    },
    {
      icon: ShieldCheck,
      title: 'Quest Connects',
      desc: 'On your Quest VR headset, point the 3D Avatar to the Cloud URL. It routes requests to your PC through the tunnel.',
      color: '#14b8a6',
    },
  ]

  return (
    <div className="space-y-4">
      {steps.map((step, i) => {
        const SIcon = step.icon
        return (
          <div key={i} className="flex items-start gap-4">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 mt-0.5"
              style={{
                background: `linear-gradient(135deg, ${step.color}15, ${step.color}08)`,
                border: `1px solid ${step.color}25`,
              }}
            >
              <SIcon size={16} style={{ color: step.color }} />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-0.5">
                <span
                  className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                  style={{ background: `${step.color}15`, color: step.color }}
                >
                  Step {i + 1}
                </span>
                <h3 className="text-sm font-medium text-white/80">{step.title}</h3>
              </div>
              <p className="text-xs text-white/40 leading-relaxed">{step.desc}</p>
            </div>
          </div>
        )
      })}

      <div
        className="mt-4 px-4 py-3 rounded-xl"
        style={{
          background: 'rgba(20,184,166,0.05)',
          border: '1px solid rgba(20,184,166,0.12)',
        }}
      >
        <div className="flex items-start gap-2">
          <ShieldCheck size={14} className="text-glow-teal shrink-0 mt-0.5" />
          <p className="text-xs text-glow-teal/80 leading-relaxed">
            <strong>Privacy first:</strong> Your model weights and data never leave your PC.
            Only API requests and responses pass through the encrypted tunnel.
            No port forwarding or static IP needed.
          </p>
        </div>
      </div>
    </div>
  )
}

// ── Architecture Diagram ────────────────────────────────────────────

function ArchitectureDiagram({ status }: { status: CloudStatus }) {
  const connected = status.state === 'connected'
  return (
    <div
      className="rounded-xl px-5 py-4 font-mono text-[11px] leading-relaxed overflow-x-auto"
      style={{
        background: 'rgba(0,0,0,0.25)',
        border: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <pre className="text-white/40">
{`  Your PC (GPU)              OllaBridge Cloud            Oculus Quest
  ┌───────────────┐         ┌──────────────┐         ┌─────────────┐
  │ Ollama        │         │              │         │ 3D Avatar   │
  │ HomePilot     │◄──`}<span style={{ color: connected ? '#14b8a6' : '#6b7280' }}>{connected ? ' WSS ' : ' ··· '}</span>{`──►│  Relay Hub   │◄──HTTPS──│ Chatbot     │
  │ OllaBridge    │         │              │         │             │
  └───────────────┘         └──────────────┘         └─────────────┘
        `}<span style={{ color: connected ? '#14b8a6' : '#6b7280' }}>{connected ? '● Connected' : '○ Not linked'}</span></pre>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────────

export function CloudPage() {
  const { data: status } = useCloudStatus()
  const cloudStatus: CloudStatus = status || {
    state: 'disconnected',
    cloud_url: '',
    device_id: '',
    models_shared: [],
    models_count: 0,
    connected_since: null,
    uptime_seconds: null,
    last_error: '',
    pairing_code: '',
    pairing_expires_at: 0,
    reconnect_attempt: 0,
  }

  const stateColor = STATE_COLORS[cloudStatus.state] || '#6b7280'

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-6 py-6 space-y-6">
        {/* Connection Status */}
        <GlassCard>
          <SectionTitle
            icon={Cloud}
            title="Cloud Relay"
            subtitle="Connect your GPU to OllaBridge Cloud for Quest VR access"
            color={stateColor}
            badge={{
              label: STATE_LABELS[cloudStatus.state],
              color: stateColor,
            }}
          />
          <ConnectionStatusCard status={cloudStatus} />
        </GlassCard>

        {/* Pairing Flow (only when not connected) */}
        {cloudStatus.state !== 'connected' && (
          <GlassCard delay={0.05}>
            <SectionTitle
              icon={Link2}
              title="Link to Cloud"
              subtitle="Pair this PC with your OllaBridge Cloud instance"
              color="#00e5ff"
            />
            <PairingSection status={cloudStatus} />
          </GlassCard>
        )}

        {/* Architecture */}
        <GlassCard delay={0.1}>
          <SectionTitle
            icon={Wifi}
            title="Architecture"
            subtitle="How your PC connects to Quest VR through the cloud"
            color="#8b5cf6"
          />
          <ArchitectureDiagram status={cloudStatus} />
        </GlassCard>

        {/* How It Works */}
        <GlassCard delay={0.15}>
          <SectionTitle
            icon={Zap}
            title="How It Works"
            subtitle="Three steps to connect your Quest to your GPU"
            color="#14b8a6"
          />
          <HowItWorks />
        </GlassCard>
      </div>
    </div>
  )
}
