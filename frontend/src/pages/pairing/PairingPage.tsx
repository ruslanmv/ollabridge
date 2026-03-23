import { useState, useCallback, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Link2,
  Smartphone,
  Trash2,
  Copy,
  Check,
  RefreshCw,
  Home,
  Bot,
  ArrowRight,
  Shield,
  Wifi,
  Key,
  Clock,
  Plus,
  Globe,
  Zap,
  Eye,
  EyeOff,
} from 'lucide-react'
import { usePairInfo, useConnectionInfo } from '../../lib/hooks'
import { api, type PairedDevice } from '../../lib/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

// ── Helpers ─────────────────────────────────────────────────────────────

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
  icon: typeof Link2
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

function CopyButton({ text, label }: { text: string; label?: string }) {
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
      {label || (copied ? 'Copied' : 'Copy')}
    </motion.button>
  )
}

// ── Auth Mode Status ────────────────────────────────────────────────────

function AuthModeStatus({ authMode }: { authMode: string }) {
  const modes = [
    {
      value: 'required',
      label: 'API Key Required',
      desc: 'Static API keys authenticate all requests',
      color: '#f59e0b',
      icon: Key,
    },
    {
      value: 'local-trust',
      label: 'Local Trust',
      desc: 'Skip auth for localhost connections',
      color: '#14b8a6',
      icon: Shield,
    },
    {
      value: 'pairing',
      label: 'Device Pairing',
      desc: 'Pair devices with short-lived codes for bearer tokens',
      color: '#8b5cf6',
      icon: Link2,
    },
  ]

  return (
    <div className="space-y-3">
      <p className="text-xs text-white/40 uppercase tracking-wider font-medium">
        Authentication Mode
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {modes.map((mode) => {
          const active = authMode === mode.value
          const ModeIcon = mode.icon
          return (
            <div
              key={mode.value}
              className="px-4 py-3 rounded-xl transition-colors"
              style={{
                background: active
                  ? `linear-gradient(135deg, ${mode.color}12, ${mode.color}06)`
                  : 'rgba(255,255,255,0.02)',
                border: active
                  ? `1px solid ${mode.color}40`
                  : '1px solid rgba(255,255,255,0.06)',
              }}
            >
              <div className="flex items-center gap-2 mb-1">
                <ModeIcon size={14} style={{ color: active ? mode.color : 'rgba(255,255,255,0.3)' }} />
                <span
                  className="text-sm font-medium"
                  style={{ color: active ? mode.color : 'rgba(255,255,255,0.4)' }}
                >
                  {mode.label}
                </span>
                {active && (
                  <span
                    className="ml-auto px-1.5 py-0.5 rounded text-[9px] font-bold uppercase"
                    style={{
                      background: `${mode.color}20`,
                      color: mode.color,
                    }}
                  >
                    Active
                  </span>
                )}
              </div>
              <p className="text-[11px] text-white/30">{mode.desc}</p>
            </div>
          )
        })}
      </div>
      <p className="text-[11px] text-white/25">
        Auth mode is set via AUTH_MODE environment variable (restart required to change).
      </p>
    </div>
  )
}

// ── Pairing Code Generator ──────────────────────────────────────────────

function PairingCodeSection() {
  const { data: pairInfo, isLoading } = usePairInfo()
  const queryClient = useQueryClient()
  const [generatedCode, setGeneratedCode] = useState<{
    code: string
    display: string
    ttl: number
    generatedAt: number
  } | null>(null)

  const generateMutation = useMutation({
    mutationFn: () => api.pairGenerate(),
    onSuccess: (data) => {
      setGeneratedCode({
        code: data.code,
        display: data.code_display,
        ttl: data.ttl,
        generatedAt: Date.now() / 1000,
      })
      queryClient.invalidateQueries({ queryKey: ['pairInfo'] })
    },
  })

  // Countdown timer for generated code
  const [remaining, setRemaining] = useState(0)
  useEffect(() => {
    if (!generatedCode) return
    const update = () => {
      const elapsed = Date.now() / 1000 - generatedCode.generatedAt
      const left = Math.max(0, generatedCode.ttl - elapsed)
      setRemaining(Math.ceil(left))
      if (left <= 0) setGeneratedCode(null)
    }
    update()
    const iv = setInterval(update, 1000)
    return () => clearInterval(iv)
  }, [generatedCode])

  // Also track server-side active code
  const serverCodeActive = pairInfo?.pairing_available
  const serverCodeDisplay = pairInfo?.code_display
  const serverTtl = pairInfo?.ttl_remaining ?? 0

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <RefreshCw size={16} className="text-white/20 animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/* Generate button */}
      <div className="flex items-center gap-4">
        <motion.button
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all disabled:opacity-50"
          style={{
            background: 'linear-gradient(135deg, rgba(139,92,246,0.2), rgba(0,229,255,0.15))',
            border: '1px solid rgba(139,92,246,0.3)',
            color: '#8b5cf6',
          }}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
        >
          {generateMutation.isPending ? (
            <RefreshCw size={14} className="animate-spin" />
          ) : (
            <Plus size={14} />
          )}
          Generate Pairing Code
        </motion.button>

        <div className="text-xs text-white/30 flex items-center gap-1.5">
          <Clock size={12} />
          Codes expire in {pairInfo?.code_ttl ?? 300}s
        </div>
      </div>

      {/* Active code display */}
      <AnimatePresence mode="wait">
        {(generatedCode || serverCodeActive) && (
          <motion.div
            className="rounded-2xl overflow-hidden"
            style={{
              background: 'linear-gradient(135deg, rgba(139,92,246,0.08), rgba(0,229,255,0.05))',
              border: '1px solid rgba(139,92,246,0.2)',
            }}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
          >
            <div className="px-6 py-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs text-white/40 uppercase tracking-wider font-medium">
                  Active Pairing Code
                </span>
                <div className="flex items-center gap-2">
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{
                      background: 'radial-gradient(circle, #8b5cf6 30%, transparent 100%)',
                      boxShadow: '0 0 6px rgba(139,92,246,0.6)',
                    }}
                  />
                  <span className="text-xs text-glow-violet/70">
                    {generatedCode ? remaining : serverTtl}s remaining
                  </span>
                </div>
              </div>

              {/* Big code display */}
              <div className="flex items-center gap-4">
                <code
                  className="flex-1 text-center text-4xl font-mono font-bold tracking-[0.4em] py-3 select-all"
                  style={{ color: '#8b5cf6', textShadow: '0 0 20px rgba(139,92,246,0.4)' }}
                >
                  {generatedCode?.display || serverCodeDisplay || '---'}
                </code>
                <CopyButton
                  text={generatedCode?.code || serverCodeDisplay?.replace('-', '') || ''}
                  label="Copy Code"
                />
              </div>

              <p className="text-xs text-white/30 mt-3">
                Share this code with the device you want to pair. The device enters this code to get a bearer token.
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* No code state */}
      {!generatedCode && !serverCodeActive && (
        <div className="py-4 text-center text-white/25 text-sm">
          No active pairing code. Generate one to start pairing a device.
        </div>
      )}
    </div>
  )
}

// ── Paired Devices List ─────────────────────────────────────────────────

function DevicesList() {
  const {
    data: devicesData,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['pairDevices'],
    queryFn: api.pairDevices,
    refetchInterval: 15_000,
    retry: false,
  })
  const queryClient = useQueryClient()

  const revokeMutation = useMutation({
    mutationFn: (deviceId: string) => api.pairRevoke(deviceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pairDevices'] })
      queryClient.invalidateQueries({ queryKey: ['pairInfo'] })
    },
  })

  const devices = devicesData?.devices ?? []

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-white/40 uppercase tracking-wider">
          Paired devices ({devices.length})
        </span>
        <button
          onClick={() => refetch()}
          className="p-1.5 rounded-lg text-white/30 hover:text-white/60 hover:bg-white/5 transition-colors"
        >
          <RefreshCw size={12} />
        </button>
      </div>

      {isLoading && (
        <div className="py-6 text-center">
          <RefreshCw size={16} className="text-white/20 animate-spin mx-auto" />
        </div>
      )}

      {!isLoading && devices.length === 0 && (
        <div className="py-8 text-center text-white/20 text-sm">
          No devices paired yet. Generate a code above and enter it on the device to pair.
        </div>
      )}

      <div className="space-y-2">
        <AnimatePresence>
          {devices.map((device: PairedDevice, i: number) => (
            <motion.div
              key={device.device_id}
              className="flex items-center gap-3 px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06] hover:border-white/10 transition-colors group"
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 12 }}
              transition={{ delay: i * 0.05 }}
            >
              <Smartphone size={16} className="text-glow-violet shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white/80 truncate">{device.label}</p>
                <p className="text-xs text-white/30 font-mono truncate">
                  {device.device_id}
                </p>
              </div>
              <span className="text-xs text-white/20 shrink-0">
                {new Date(Number(device.paired_at) * 1000).toLocaleDateString()}
              </span>
              <button
                onClick={() => {
                  if (confirm(`Revoke access for "${device.label}"?`)) {
                    revokeMutation.mutate(device.device_id)
                  }
                }}
                disabled={revokeMutation.isPending}
                className="p-1.5 rounded-lg text-white/20 hover:text-glow-pink hover:bg-glow-pink/10 transition-colors opacity-0 group-hover:opacity-100"
                title="Revoke device access"
              >
                <Trash2 size={14} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  )
}

// ── Connection Guide ────────────────────────────────────────────────────

function ConnectionGuide({
  icon: Icon,
  title,
  color,
  steps,
}: {
  icon: typeof Home
  title: string
  color: string
  steps: string[]
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Icon size={16} style={{ color }} />
        <h3 className="text-sm font-medium text-white/80">{title}</h3>
      </div>
      <ol className="space-y-2 pl-1">
        {steps.map((step, i) => (
          <li key={i} className="flex items-start gap-3 text-xs text-white/50">
            <span
              className="shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold mt-0.5"
              style={{
                background: `${color}15`,
                color,
                border: `1px solid ${color}30`,
              }}
            >
              {i + 1}
            </span>
            <span className="leading-relaxed pt-0.5">{step}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

// ── Client Configuration Card ───────────────────────────────────────────

function ClientConfigCard() {
  const { data: connInfo, isLoading } = useConnectionInfo()
  const [showKey, setShowKey] = useState(false)

  if (isLoading || !connInfo) {
    return (
      <div className="flex items-center justify-center py-8">
        <RefreshCw size={16} className="text-white/20 animate-spin" />
      </div>
    )
  }

  const fields = [
    {
      label: 'Base URL',
      value: connInfo.base_url,
      mono: true,
      icon: Globe,
      color: '#00e5ff',
    },
    {
      label: 'API Key',
      value: showKey ? connInfo.api_key : connInfo.api_key_masked,
      rawValue: connInfo.api_key,
      mono: true,
      icon: Key,
      color: '#f59e0b',
      secret: true,
    },
    {
      label: 'Default Model',
      value: connInfo.default_model,
      mono: true,
      icon: Zap,
      color: '#8b5cf6',
    },
  ]

  return (
    <div className="space-y-4">
      <p className="text-xs text-white/40">
        Use these settings to connect any OpenAI-compatible client (HomePilot, 3D Avatar, curl, etc.)
      </p>

      {/* Config fields */}
      <div className="space-y-3">
        {fields.map((f) => {
          const FIcon = f.icon
          return (
            <div
              key={f.label}
              className="flex items-center gap-3 px-4 py-3 rounded-xl"
              style={{
                background: 'rgba(255,255,255,0.02)',
                border: '1px solid rgba(255,255,255,0.06)',
              }}
            >
              <FIcon size={14} style={{ color: f.color }} className="shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-[10px] text-white/35 uppercase tracking-wider mb-0.5">{f.label}</p>
                <code className="text-sm text-white/80 font-mono block truncate">
                  {f.value}
                </code>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {f.secret && (
                  <motion.button
                    onClick={() => setShowKey(!showKey)}
                    className="p-1.5 rounded-lg text-white/25 hover:text-white/50 transition-colors"
                    whileTap={{ scale: 0.9 }}
                  >
                    {showKey ? <EyeOff size={13} /> : <Eye size={13} />}
                  </motion.button>
                )}
                <CopyButton text={f.rawValue || f.value} />
              </div>
            </div>
          )
        })}
      </div>

      {/* Available models */}
      {connInfo.models.length > 0 && (
        <div className="mt-2">
          <p className="text-[10px] text-white/35 uppercase tracking-wider mb-2">Available Models</p>
          <div className="flex flex-wrap gap-1.5">
            {connInfo.models.map((m) => (
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

      {/* Quick usage example */}
      <div
        className="mt-3 px-4 py-3 rounded-xl"
        style={{
          background: 'rgba(0,0,0,0.2)',
          border: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <div className="flex items-center justify-between mb-2">
          <p className="text-[10px] text-white/30 uppercase tracking-wider font-medium">Quick Test</p>
          <CopyButton
            text={`curl ${connInfo.base_url}/chat/completions \\\n  -H "Authorization: Bearer ${connInfo.api_key}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${connInfo.default_model}", "messages": [{"role": "user", "content": "Hello"}]}'`}
            label="Copy curl"
          />
        </div>
        <pre className="text-[11px] text-glow-cyan/60 font-mono whitespace-pre-wrap break-all leading-relaxed">
{`curl ${connInfo.base_url}/chat/completions \\
  -H "Authorization: Bearer ${connInfo.api_key_masked}" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${connInfo.default_model}", ...}'`}
        </pre>
      </div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────────────

export function PairingPage() {
  const { data: pairInfo } = usePairInfo()
  const authMode = pairInfo?.auth_mode ?? 'required'

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-6 py-6 space-y-6">
        {/* Client Configuration — the essential info for connecting */}
        <GlassCard>
          <SectionTitle
            icon={Globe}
            title="Client Configuration"
            subtitle="Connection details for OpenAI-compatible clients"
            color="#00e5ff"
            badge={{ label: 'OllaBridge', color: '#00e5ff' }}
          />
          <ClientConfigCard />
        </GlassCard>

        {/* Auth Mode Overview */}
        <GlassCard>
          <SectionTitle
            icon={Shield}
            title="Authentication"
            subtitle="Current authentication mode and pairing status"
            color="#f59e0b"
            badge={{
              label: authMode,
              color: authMode === 'pairing' ? '#8b5cf6' : authMode === 'local-trust' ? '#14b8a6' : '#f59e0b',
            }}
          />
          <AuthModeStatus authMode={authMode} />
        </GlassCard>

        {/* Generate Pairing Code (admin tool) */}
        <GlassCard delay={0.05}>
          <SectionTitle
            icon={Link2}
            title="Pairing Codes"
            subtitle="Generate codes to pair new devices to this gateway"
            color="#8b5cf6"
            badge={
              pairInfo?.pairing_available
                ? { label: 'Code Active', color: '#14b8a6' }
                : undefined
            }
          />
          <PairingCodeSection />
        </GlassCard>

        {/* Paired Devices */}
        <GlassCard delay={0.1}>
          <SectionTitle
            icon={Smartphone}
            title="Paired Devices"
            subtitle="Clients currently connected to this OllaBridge gateway"
            color="#8b5cf6"
            badge={{
              label: `${pairInfo?.device_count ?? 0} connected`,
              color: '#8b5cf6',
            }}
          />
          <DevicesList />
        </GlassCard>

        {/* Connection Guides */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <GlassCard delay={0.2}>
            <SectionTitle
              icon={Home}
              title="Connect HomePilot"
              subtitle="Smart home AI assistant"
              color="#14b8a6"
            />
            <ConnectionGuide
              icon={Home}
              title="Setup Steps"
              color="#14b8a6"
              steps={[
                'Enable HomePilot integration in Settings',
                'Set your HomePilot base URL (default: localhost:8000)',
                'Add the HomePilot API key if authentication is required',
                'OllaBridge will register HomePilot personas as models',
                'Use the paired token as Bearer auth for API calls',
              ]}
            />
            <div className="mt-4 flex items-center gap-2 px-3 py-2 rounded-lg bg-glow-teal/5 border border-glow-teal/10">
              <Wifi size={14} className="text-glow-teal shrink-0" />
              <span className="text-xs text-glow-teal/80">
                HomePilot personas become available as models via /v1/chat/completions
              </span>
            </div>
          </GlassCard>

          <GlassCard delay={0.25}>
            <SectionTitle
              icon={Bot}
              title="Connect 3D Avatar"
              subtitle="3D Avatar Chatbot interface"
              color="#8b5cf6"
            />
            <ConnectionGuide
              icon={Bot}
              title="Setup Steps"
              color="#8b5cf6"
              steps={[
                'Configure the 3D Avatar Chatbot to point at this OllaBridge',
                "Set the API base URL to this gateway's address",
                'Use the paired device token as the API key',
                'Select a model (or HomePilot persona) for the avatar',
                'The avatar will route requests through OllaBridge to Ollama or HomePilot',
              ]}
            />
            <div className="mt-4 flex items-center gap-2 px-3 py-2 rounded-lg bg-glow-violet/5 border border-glow-violet/10">
              <ArrowRight size={14} className="text-glow-violet shrink-0" />
              <span className="text-xs text-glow-violet/80">
                3D Avatar &rarr; OllaBridge &rarr; HomePilot / Ollama
              </span>
            </div>
          </GlassCard>
        </div>
      </div>
    </div>
  )
}
