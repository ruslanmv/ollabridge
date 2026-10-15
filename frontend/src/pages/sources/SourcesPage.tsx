import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Cloud, Home, RefreshCw, Save, Server, Wand2 } from 'lucide-react'
import { motion } from 'framer-motion'
import {
  api,
  type GatewaySettings,
  type SourceHealthRequest,
  type SourceHealthResponse,
} from '../../lib/api'
import { useModelAccess, useModels, useSetModelAccess, useSettings } from '../../lib/hooks'
import { isHomePilotModel, isOllamaModel } from '../../lib/modelSource'
import { ExternalRuntimes } from './ExternalRuntimes'
import { ModelPill } from './ui'
import { OllamaSetupWizard } from './OllamaSetupWizard'
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
  disabled = false,
}: {
  enabled: boolean
  onToggle: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      className={`relative w-14 h-8 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
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

type OllamaProbe = {
  data?: SourceHealthResponse
  isError: boolean
  isFetching: boolean
}

/**
 * What the Ollama card says when `/v1/models` attributes nothing to Ollama.
 *
 * An empty list is ambiguous on its own: the runtime may be down, or up with
 * nothing pulled yet, and the registry never marks the local node unhealthy.
 * The probe (the same call as "Test Connection") settles it, so the card can
 * say "not reachable" rather than borrowing another runtime's models.
 */
function SetupButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
      style={{
        background: 'linear-gradient(135deg, rgba(0,229,255,0.18), rgba(139,92,246,0.14))',
        border: '1px solid rgba(0,229,255,0.3)',
        color: '#00e5ff',
      }}
    >
      <Wand2 size={12} /> {label}
    </button>
  )
}

function OllamaEmptyState({
  enabled,
  url,
  probe,
  onSetup,
}: {
  enabled: boolean
  url: string
  probe: OllamaProbe
  onSetup: () => void
}) {
  const where = url || 'the configured base URL'

  if (!enabled) {
    return (
      <div className="w-full flex items-center justify-between gap-3">
        <span className="text-xs text-white/30">
          Ollama is switched off on this device. Enable it above and save, or let the wizard do it.
        </span>
        <SetupButton onClick={onSetup} label="Set up Ollama" />
      </div>
    )
  }

  if (probe.data?.reachable) {
    return (
      <div className="w-full rounded-xl px-3 py-2 text-xs border text-amber-200 bg-amber-500/10 border-amber-500/20 flex items-center justify-between gap-3">
        <span>
          Ollama is reachable at <span className="font-mono">{where}</span> but has no models
          pulled yet.
        </span>
        <SetupButton onClick={onSetup} label="Pull a first model" />
      </div>
    )
  }

  if (probe.data || probe.isError) {
    return (
      <div className="w-full rounded-xl px-3 py-2 text-xs border text-red-300 bg-red-500/10 border-red-500/20">
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} className="shrink-0" />
          <span className="flex-1">
            Ollama not reachable at <span className="font-mono">{where}</span>
          </span>
          <SetupButton onClick={onSetup} label="Set up Ollama" />
        </div>
        {probe.data?.message ? (
          <div className="text-red-200/70 mt-1 ml-6">{probe.data.message}</div>
        ) : null}
      </div>
    )
  }

  return (
    <span className="text-xs text-white/30">
      {probe.isFetching ? `Checking Ollama at ${where}…` : 'No Ollama models discovered yet.'}
    </span>
  )
}

export function SourcesPage({ onNavigate }: SourcesPageProps) {
  const queryClient = useQueryClient()
  const { data: settings, isLoading: settingsLoading } = useSettings()
  const { data: modelsData, isLoading: modelsLoading } = useModels()
  const modelAccess = useModelAccess()
  const setModelAccess = useSetModelAccess()

  const [form, setForm] = useState<GatewaySettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [testingSource, setTestingSource] = useState<'ollama' | 'homepilot' | null>(null)
  const [setupOpen, setSetupOpen] = useState(false)
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
  }, [settings])

  // Only what the gateway attributes to Ollama. Filtering by id prefix used
  // to count every Open WebUI and BYOK model here while Ollama was down.
  const ollamaModels = useMemo(
    () => (modelsData?.data ?? []).filter(isOllamaModel),
    [modelsData],
  )

  const homepilotModels = useMemo(
    () => (modelsData?.data ?? []).filter(isHomePilotModel),
    [modelsData],
  )

  // Probe the saved URL (not the one being typed) only while the list is
  // empty, to tell "down" from "nothing pulled". See OllamaEmptyState.
  const savedOllamaUrl = settings?.ollama_base_url ?? ''
  const ollamaEnabled = settings?.local_runtime_enabled ?? true
  const ollamaProbe = useQuery({
    queryKey: ['sourceHealth', 'ollama', savedOllamaUrl],
    queryFn: () => api.sourceHealth({ source: 'ollama', base_url: savedOllamaUrl }),
    enabled: ollamaEnabled && !!savedOllamaUrl && !modelsLoading && ollamaModels.length === 0,
    refetchInterval: 30_000,
    retry: false,
  })

  const ollamaAccessModels = useMemo(() => {
    return modelAccess.data?.sources.find((src) => src.source_id === 'ollama')?.models ?? []
  }, [modelAccess.data])

  const sharedOllamaCount = useMemo(() => {
    return ollamaAccessModels.filter((m) => m.enabled && m.visible_cloud).length
  }, [ollamaAccessModels])

  const allOllamaShared = ollamaAccessModels.length > 0 && sharedOllamaCount === ollamaAccessModels.length

  async function toggleOllamaSharing() {
    if (ollamaAccessModels.length === 0) return

    const nextVisible = !allOllamaShared
    setMessage(null)
    setError(null)

    try {
      await Promise.all(
        ollamaAccessModels.map((model) =>
          setModelAccess.mutateAsync({
            sourceId: model.source_id,
            modelId: model.model_id,
            body: { visible_cloud: nextVisible },
          }),
        ),
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['modelAccess'] }),
        queryClient.invalidateQueries({ queryKey: ['cloudModelManifest'] }),
        queryClient.invalidateQueries({ queryKey: ['cloudStatus'] }),
      ])
      setMessage(
        nextVisible
          ? 'All discovered Ollama models are now shared with OllaBridge Cloud'
          : 'Ollama model sharing is disabled for this device',
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update Ollama model sharing')
    }
  }

  async function saveSettings() {
    if (!form) return
    setSaving(true)
    setMessage(null)
    setError(null)

    try {
      // The Enable toggles ARE the source of truth — there is no "mode".
      const patch: Partial<GatewaySettings> = {
        local_runtime_enabled: form.local_runtime_enabled,
        homepilot_enabled: form.homepilot_enabled,
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
        queryClient.invalidateQueries({ queryKey: ['modelAccess'] }),
        queryClient.invalidateQueries({ queryKey: ['cloudModelManifest'] }),
        queryClient.invalidateQueries({ queryKey: ['cloudStatus'] }),
      ])

      setMessage('Runtimes saved successfully')

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
            <h1 className="text-xl font-bold text-white/90">Local Runtimes</h1>
            <p className="text-sm text-white/40 mt-1">
              Execution backends on this device — Ollama models and HomePilot personas. To
              connect external accounts, use Sources. Local Ollama models are shared with Cloud
              by default and can be disabled here.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ['settings'] })
              queryClient.invalidateQueries({ queryKey: ['models'] })
              queryClient.invalidateQueries({ queryKey: ['modelAccess'] })
              queryClient.invalidateQueries({ queryKey: ['cloudModelManifest'] })
              queryClient.invalidateQueries({ queryKey: ['cloudStatus'] })
            }}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm text-white/70 bg-white/[0.04] border border-white/10 hover:bg-white/[0.06]"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
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
              label="Share Ollama models"
              description="Publish every discovered Ollama model to OllaBridge Cloud; turn off to share none"
            >
              <div className="flex items-center justify-end gap-3">
                <div className="text-right">
                  <div className="inline-flex items-center gap-1.5 text-xs text-white/55">
                    {allOllamaShared ? (
                      <CheckCircle2 size={13} className="text-emerald-300" />
                    ) : (
                      <Cloud size={13} className="text-white/35" />
                    )}
                    <span>
                      {modelAccess.isLoading
                        ? 'Checking sharing…'
                        : `${sharedOllamaCount}/${ollamaAccessModels.length} shared`}
                    </span>
                  </div>
                  <div className="text-[10px] text-white/30 mt-0.5">
                    Per-model control remains available in Sources → Models & Access
                  </div>
                </div>
                <Toggle
                  enabled={allOllamaShared}
                  onToggle={toggleOllamaSharing}
                  disabled={
                    setModelAccess.isPending ||
                    modelAccess.isLoading ||
                    ollamaAccessModels.length === 0
                  }
                />
              </div>
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
                  : `${ollamaModels.length} Ollama model${ollamaModels.length === 1 ? '' : 's'} discovered`}
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
              ) : modelsLoading ? (
                <span className="text-xs text-white/30">Checking Ollama models…</span>
              ) : (
                <OllamaEmptyState
                  enabled={ollamaEnabled}
                  url={savedOllamaUrl}
                  probe={ollamaProbe}
                  onSetup={() => setSetupOpen(true)}
                />
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
                  : `${homepilotModels.length} HomePilot persona model${homepilotModels.length === 1 ? '' : 's'} discovered`}
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

        {/* External accounts acting as runtimes. Configured in Sources; shown
            here because a routing-enabled source serves requests exactly like
            a local backend does, and is published to Cloud alongside them. */}
        <ExternalRuntimes onNavigate={onNavigate} />

        {/* Few-clicks path to a working local runtime; opens on the step
            that matters (install / start / connect / first model). */}
        {setupOpen && (
          <OllamaSetupWizard onClose={() => setSetupOpen(false)} onNavigate={onNavigate} />
        )}

        <div className="flex justify-end">
          <button
            type="button"
            disabled={saving}
            onClick={saveSettings}
            className="inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-medium text-cyan-300 bg-cyan-500/10 border border-cyan-400/20 hover:bg-cyan-500/15 disabled:opacity-50"
          >
            <Save size={15} />
            {saving ? 'Saving…' : 'Save Runtimes'}
          </button>
        </div>
      </div>
    </div>
  )
}
