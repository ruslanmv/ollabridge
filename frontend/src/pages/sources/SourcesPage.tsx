import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Home, RefreshCw, Save, Server } from 'lucide-react'
import { motion } from 'framer-motion'
import {
  api,
  deriveSourceMode,
  type GatewaySettings,
  type SourceMode,
  type SourceHealthRequest,
} from '../../lib/api'
import { useModels, useSettings } from '../../lib/hooks'
import type { Page } from '../../App'

type SourceHealthResult = {
  ok: boolean
  source: SourceHealthRequest['source']
  reachable: boolean
  status_code?: number
  message: string
  models: string[]
}

type SourcesPageProps = {
  onNavigate?: (page: Page) => void
}

function SectionCard({
  title,
  subtitle,
  icon: Icon,
  color,
  children,
}: {
  title: string
  subtitle: string
  icon: typeof Home
  color: string
  children: React.ReactNode
}) {
  return (
    <motion.div
      className="glass-card p-6"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className="flex items-center gap-3 mb-5">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center"
          style={{
            background: `linear-gradient(135deg, ${color}20, ${color}08)`,
            border: `1px solid ${color}30`,
          }}
        >
          <Icon size={18} style={{ color }} />
        </div>
        <div>
          <h2 className="text-white/90 font-semibold text-base">{title}</h2>
          <p className="text-white/40 text-xs">{subtitle}</p>
        </div>
      </div>
      {children}
    </motion.div>
  )
}

function Field({
  label,
  description,
  children,
}: {
  label: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <div className="py-3 border-b border-white/[0.05] last:border-b-0">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="text-sm text-white/75 font-medium">{label}</div>
          {description ? <div className="text-xs text-white/35 mt-0.5">{description}</div> : null}
        </div>
        <div className="w-[320px] max-w-full">{children}</div>
      </div>
    </div>
  )
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full rounded-xl px-3 py-2.5 text-sm text-white/85 bg-white/[0.04] border border-white/10 outline-none focus:border-cyan-400/50"
    />
  )
}

function Toggle({
  enabled,
  onToggle,
}: {
  enabled: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`relative w-14 h-8 rounded-full transition-colors ${
        enabled ? 'bg-cyan-500/25' : 'bg-white/10'
      } border border-white/10`}
    >
      <span
        className={`absolute top-1 w-6 h-6 rounded-full transition-all ${
          enabled ? 'left-7 bg-cyan-400' : 'left-1 bg-white/50'
        }`}
      />
    </button>
  )
}

function ModelPill({ label }: { label: string }) {
  return (
    <span className="px-2.5 py-1 rounded-full text-xs text-cyan-300 bg-cyan-400/10 border border-cyan-400/15">
      {label}
    </span>
  )
}

function ModeButton({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-2 rounded-xl text-sm border transition-colors ${
        active
          ? 'text-cyan-300 bg-cyan-500/10 border-cyan-400/20'
          : 'text-white/55 bg-white/[0.03] border-white/10 hover:bg-white/[0.05]'
      }`}
    >
      {label}
    </button>
  )
}

function inferMode(settings: GatewaySettings): SourceMode {
  return deriveSourceMode(settings)
}

function modeToPatch(mode: SourceMode): Partial<GatewaySettings> {
  if (mode === 'hybrid') {
    return {
      local_runtime_enabled: true,
      homepilot_enabled: true,
    }
  }
  if (mode === 'homepilot') {
    return {
      local_runtime_enabled: false,
      homepilot_enabled: true,
    }
  }
  return {
    local_runtime_enabled: true,
    homepilot_enabled: false,
  }
}

export function SourcesPage({ onNavigate }: SourcesPageProps) {
  const queryClient = useQueryClient()
  const { data: settings, isLoading: settingsLoading } = useSettings()
  const { data: modelsData, isLoading: modelsLoading } = useModels()

  const [form, setForm] = useState<GatewaySettings | null>(null)
  const [mode, setMode] = useState<SourceMode>('ollama')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [testingSource, setTestingSource] = useState<'ollama' | 'homepilot' | null>(null)
  const [sourceResults, setSourceResults] = useState<Record<string, SourceHealthResult | null>>({
    ollama: null,
    homepilot: null,
  })

  useEffect(() => {
    if (!settings) return

    setForm({
      ...settings,
      homepilot_api_key: '',
    })
    setMode(inferMode(settings))
  }, [settings])

  const ollamaModels = useMemo(() => {
    return (modelsData?.data ?? []).filter(
      (m) => !m.id.startsWith('persona:') && !m.id.startsWith('personality:')
    )
  }, [modelsData])

  const homepilotModels = useMemo(() => {
    return (modelsData?.data ?? []).filter(
      (m) => m.id.startsWith('persona:') || m.id.startsWith('personality:')
    )
  }, [modelsData])

  async function saveSettings() {
    if (!form) return
    setSaving(true)
    setMessage(null)
    setError(null)

    try {
      const patch: Partial<GatewaySettings> = {
        ...modeToPatch(mode),
        ollama_base_url: form.ollama_base_url,
        default_model: form.default_model,
        homepilot_base_url: form.homepilot_base_url,
        ...(form.homepilot_api_key ? { homepilot_api_key: form.homepilot_api_key } : {}),
        homepilot_node_id: form.homepilot_node_id || 'homepilot',
        homepilot_node_tags: form.homepilot_node_tags || 'homepilot,persona',
      }

      await api.updateSettings(patch)

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['settings'] }),
        queryClient.invalidateQueries({ queryKey: ['models'] }),
        queryClient.invalidateQueries({ queryKey: ['runtimes'] }),
        queryClient.invalidateQueries({ queryKey: ['health'] }),
      ])

      setMessage('Sources saved successfully')

      if (onNavigate) {
        // kept optional for future UX flows; no automatic navigation for now
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save sources')
    } finally {
      setSaving(false)
    }
  }

  async function testSource(source: 'ollama' | 'homepilot') {
    if (!form) return

    setTestingSource(source)
    setError(null)

    try {
      const result = await api.sourceHealth({
        source,
        base_url: source === 'ollama' ? form.ollama_base_url : form.homepilot_base_url,
        api_key:
          source === 'homepilot' && form.homepilot_api_key
            ? form.homepilot_api_key
            : undefined,
      })

      setSourceResults((prev) => ({ ...prev, [source]: result as SourceHealthResult }))
    } catch (e) {
      setSourceResults((prev) => ({
        ...prev,
        [source]: {
          ok: false,
          source,
          reachable: false,
          message: e instanceof Error ? e.message : 'Unexpected error',
          models: [],
        },
      }))
    } finally {
      setTestingSource(null)
    }
  }

  if (settingsLoading || !form) {
    return (
      <div className="h-full overflow-y-auto px-6 py-6">
        <div className="text-white/40 text-sm">Loading sources…</div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-6">
      <div className="max-w-6xl mx-auto space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-white/90">Sources</h1>
            <p className="text-sm text-white/40 mt-1">
              Connect the intelligence providers that supply models to OllaBridge.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ['settings'] })
              queryClient.invalidateQueries({ queryKey: ['models'] })
            }}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm text-white/70 bg-white/[0.04] border border-white/10 hover:bg-white/[0.06]"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>

        <div className="glass-card p-5">
          <div className="text-sm text-white/75 font-medium mb-3">Source mode</div>
          <div className="flex flex-wrap gap-2">
            <ModeButton active={mode === 'ollama'} label="Ollama only" onClick={() => setMode('ollama')} />
            <ModeButton active={mode === 'homepilot'} label="HomePilot only" onClick={() => setMode('homepilot')} />
            <ModeButton active={mode === 'hybrid'} label="Hybrid" onClick={() => setMode('hybrid')} />
          </div>
        </div>

        {(message || error) && (
          <div
            className={`rounded-2xl px-4 py-3 text-sm border ${
              error
                ? 'text-red-300 bg-red-500/10 border-red-500/20'
                : 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20'
            }`}
          >
            <div className="flex items-center gap-2">
              {error ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
              <span>{error || message}</span>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <SectionCard
            title="Ollama"
            subtitle="Local standard models served through your Ollama runtime"
            icon={Server}
            color="#00e5ff"
          >
            <Field
              label="Enable Ollama"
              description="Register local Ollama as an active source"
            >
              <Toggle
                enabled={form.local_runtime_enabled}
                onToggle={() =>
                  setForm({
                    ...form,
                    local_runtime_enabled: !form.local_runtime_enabled,
                  })
                }
              />
            </Field>

            <Field
              label="Ollama Base URL"
              description="Usually http://localhost:11434"
            >
              <TextInput
                value={form.ollama_base_url}
                onChange={(e) =>
                  setForm({ ...form, ollama_base_url: e.target.value })
                }
                placeholder="http://localhost:11434"
              />
            </Field>

            <Field
              label="Default Model"
              description="Fallback model used when a request does not specify one"
            >
              <TextInput
                value={form.default_model}
                onChange={(e) =>
                  setForm({ ...form, default_model: e.target.value })
                }
                placeholder="llama3"
              />
            </Field>

            <div className="pt-4 flex items-center justify-between">
              <div className="text-xs text-white/40">
                {modelsLoading
                  ? 'Checking Ollama models…'
                  : `${ollamaModels.length} Ollama model(s) discovered`}
              </div>
              <button
                type="button"
                disabled={testingSource === 'ollama'}
                onClick={() => testSource('ollama')}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white/80 bg-white/[0.05] border border-white/10 hover:bg-white/[0.08] disabled:opacity-50"
              >
                {testingSource === 'ollama' ? 'Testing…' : 'Test Connection'}
              </button>
            </div>

            {sourceResults.ollama ? (
              <div
                className={`mt-3 rounded-xl px-3 py-2 text-xs border ${
                  sourceResults.ollama.ok
                    ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20'
                    : 'text-red-300 bg-red-500/10 border-red-500/20'
                }`}
              >
                {sourceResults.ollama.message}
              </div>
            ) : null}

            <div className="mt-4 flex flex-wrap gap-2">
              {ollamaModels.length > 0 ? (
                ollamaModels.map((m) => <ModelPill key={m.id} label={m.id} />)
              ) : (
                <span className="text-xs text-white/30">
                  No Ollama models discovered yet.
                </span>
              )}
            </div>
          </SectionCard>

          <SectionCard
            title="HomePilot"
            subtitle="Expose HomePilot personas and personalities as models"
            icon={Home}
            color="#14b8a6"
          >
            <Field
              label="Enable HomePilot"
              description="Turn HomePilot into a source of intelligence"
            >
              <Toggle
                enabled={form.homepilot_enabled}
                onToggle={() =>
                  setForm({
                    ...form,
                    homepilot_enabled: !form.homepilot_enabled,
                  })
                }
              />
            </Field>

            <Field
              label="HomePilot Base URL"
              description="Usually http://localhost:8000"
            >
              <TextInput
                value={form.homepilot_base_url}
                onChange={(e) =>
                  setForm({ ...form, homepilot_base_url: e.target.value })
                }
                placeholder="http://localhost:8000"
              />
            </Field>

            <Field
              label="HomePilot API Key"
              description="Leave empty if auth is disabled"
            >
              <div>
                <TextInput
                  type="password"
                  value={form.homepilot_api_key}
                  onChange={(e) =>
                    setForm({ ...form, homepilot_api_key: e.target.value })
                  }
                  placeholder="optional"
                />
                {settings?.homepilot_api_key_set ? (
                  <div className="text-xs text-white/35 mt-2">
                    A HomePilot API key is already stored. Leave this field empty to keep it unchanged.
                  </div>
                ) : null}
              </div>
            </Field>

            <Field
              label="Node Tags"
              description="Used for runtime registration and filtering"
            >
              <TextInput
                value={form.homepilot_node_tags || ''}
                onChange={(e) =>
                  setForm({ ...form, homepilot_node_tags: e.target.value })
                }
                placeholder="homepilot,persona"
              />
            </Field>

            <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-4 mt-3">
              <div className="text-sm text-white/80 font-medium mb-1">
                What happens when HomePilot is enabled?
              </div>
              <div className="text-xs text-white/45 leading-6">
                HomePilot personas and personalities are registered as models in
                OllaBridge and become available through
                <span className="text-cyan-300"> /v1/chat/completions</span>.
              </div>
            </div>

            <div className="pt-4 flex items-center justify-between">
              <div className="text-xs text-white/40">
                {modelsLoading
                  ? 'Checking HomePilot personas…'
                  : `${homepilotModels.length} HomePilot persona model(s) discovered`}
              </div>
              <button
                type="button"
                disabled={testingSource === 'homepilot'}
                onClick={() => testSource('homepilot')}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white/80 bg-white/[0.05] border border-white/10 hover:bg-white/[0.08] disabled:opacity-50"
              >
                {testingSource === 'homepilot' ? 'Testing…' : 'Test Connection'}
              </button>
            </div>

            {sourceResults.homepilot ? (
              <div
                className={`mt-3 rounded-xl px-3 py-2 text-xs border ${
                  sourceResults.homepilot.ok
                    ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20'
                    : 'text-red-300 bg-red-500/10 border-red-500/20'
                }`}
              >
                {sourceResults.homepilot.message}
              </div>
            ) : null}

            <div className="mt-4 flex flex-wrap gap-2">
              {homepilotModels.length > 0 ? (
                homepilotModels.map((m) => <ModelPill key={m.id} label={m.id} />)
              ) : (
                <span className="text-xs text-white/30">
                  No HomePilot persona models discovered yet.
                </span>
              )}
            </div>
          </SectionCard>
        </div>

        <div className="flex justify-end">
          <button
            type="button"
            disabled={saving}
            onClick={saveSettings}
            className="inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-medium text-cyan-300 bg-cyan-500/10 border border-cyan-400/20 hover:bg-cyan-500/15 disabled:opacity-50"
          >
            <Save size={15} />
            {saving ? 'Saving…' : 'Save Sources'}
          </button>
        </div>
      </div>
    </div>
  )
}
