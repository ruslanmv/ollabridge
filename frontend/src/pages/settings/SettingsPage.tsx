import { useState, useEffect, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Shield,
  Server,
  Home,
  Save,
  Check,
  AlertTriangle,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import { useHealth, useSettings } from '../../lib/hooks'
import { api } from '../../lib/api'
import { useQueryClient } from '@tanstack/react-query'
import { GlassCard, SectionTitle, SelectInput, SettingField, TextInput, Toggle } from './ui'
import { RateLimitsSection } from './RateLimitsSection'

// ── Main Page ────────────────────────────────────────────────────────────

export function SettingsPage() {
  const { data: health } = useHealth()
  const { data: serverSettings, isLoading: settingsLoading } = useSettings()
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Auth & Gateway
  const [authMode, setAuthMode] = useState('required')
  const [corsOrigins, setCorsOrigins] = useState(
    'http://localhost:5173,http://localhost:3000'
  )
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434')
  const [defaultModel, setDefaultModel] = useState('deepseek-r1')
  const [localRuntimeEnabled, setLocalRuntimeEnabled] = useState(true)

  // Pairing
  const [pairingCodeLength, setPairingCodeLength] = useState('6')
  const [pairingTtl, setPairingTtl] = useState('300')

  // HomePilot
  const [hpEnabled, setHpEnabled] = useState(false)
  const [hpBaseUrl, setHpBaseUrl] = useState('http://localhost:8000')
  const [hpApiKey, setHpApiKey] = useState('')

  // Rate limits save themselves; the section leaves its save here while it has
  // unsaved changes, so "Save Settings" saves those too.
  const saveRateLimits = useRef<(() => Promise<void>) | null>(null)

  // Load settings from backend API
  useEffect(() => {
    if (serverSettings) {
      setDefaultModel(serverSettings.default_model ?? 'deepseek-r1')
      setOllamaUrl(serverSettings.ollama_base_url ?? 'http://localhost:11434')
      setLocalRuntimeEnabled(serverSettings.local_runtime_enabled ?? true)
      setHpEnabled(serverSettings.homepilot_enabled ?? false)
      setHpBaseUrl(serverSettings.homepilot_base_url ?? 'http://localhost:8000')
      // Don't overwrite local input with masked "***" from server
      if (serverSettings.homepilot_api_key && serverSettings.homepilot_api_key !== '***') {
        setHpApiKey(serverSettings.homepilot_api_key)
      }
    }
  }, [serverSettings])

  // Fallback: load auth_mode from health
  useEffect(() => {
    if (health) {
      setAuthMode(health.auth_mode ?? 'required')
    }
  }, [health])

  const handleSave = useCallback(async () => {
    setSaving(true)
    setError(null)
    try {
      const patch: Record<string, unknown> = {
        default_model: defaultModel,
        ollama_base_url: ollamaUrl,
        local_runtime_enabled: localRuntimeEnabled,
        homepilot_enabled: hpEnabled,
        homepilot_base_url: hpBaseUrl,
      }
      // Only send API key if the user typed a new value (not the masked placeholder)
      if (hpApiKey && hpApiKey !== '***') {
        patch.homepilot_api_key = hpApiKey
      }
      await api.updateSettings(patch)
      if (saveRateLimits.current) await saveRateLimits.current()
      // Refresh related queries
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      queryClient.invalidateQueries({ queryKey: ['health'] })
      queryClient.invalidateQueries({ queryKey: ['runtimes'] })
      queryClient.invalidateQueries({ queryKey: ['models'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }, [defaultModel, ollamaUrl, localRuntimeEnabled, hpEnabled, hpBaseUrl, hpApiKey, queryClient])

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-6 py-6 space-y-6">
        <p className="text-sm text-white/40 mb-4">
          Advanced configuration. For normal setup of Ollama and HomePilot, use the Sources page.
        </p>

        {/* Loading indicator */}
        {settingsLoading && (
          <div className="flex items-center gap-2 text-white/40 text-sm py-4">
            <Loader2 size={16} className="animate-spin" />
            Loading settings from gateway...
          </div>
        )}

        {/* Authentication */}
        <GlassCard delay={0.1}>
          <SectionTitle
            icon={Shield}
            title="Authentication"
            subtitle="Control how clients authenticate with this gateway"
            color="#f59e0b"
          />

          <div className="space-y-0">
            <SettingField
              label="Auth Mode"
              description="How clients identify themselves (env-driven, restart required to change)"
            >
              <SelectInput
                value={authMode}
                onChange={setAuthMode}
                options={[
                  {
                    value: 'required',
                    label: 'Required — Static API keys',
                  },
                  {
                    value: 'local-trust',
                    label: 'Local Trust — Skip auth for localhost',
                  },
                  {
                    value: 'pairing',
                    label: 'Pairing — Device code exchange',
                  },
                ]}
              />
            </SettingField>

            <AnimatePresence>
              {authMode === 'pairing' && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.25 }}
                  className="overflow-hidden"
                >
                  <SettingField
                    label="Pairing Code Length"
                    description="Number of digits in generated codes"
                  >
                    <TextInput
                      value={pairingCodeLength}
                      onChange={setPairingCodeLength}
                      placeholder="6"
                    />
                  </SettingField>

                  <SettingField
                    label="Code TTL (seconds)"
                    description="How long a pairing code stays valid"
                  >
                    <TextInput
                      value={pairingTtl}
                      onChange={setPairingTtl}
                      placeholder="300"
                    />
                  </SettingField>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </GlassCard>

        {/* Gateway Settings */}
        <GlassCard delay={0.15}>
          <SectionTitle
            icon={Server}
            title="Gateway"
            subtitle="Core OllaBridge server configuration"
          />

          <div className="space-y-0">
            <SettingField
              label="Local Ollama Runtime"
              description="Register local Ollama as a backend node"
            >
              <Toggle
                enabled={localRuntimeEnabled}
                onToggle={() => setLocalRuntimeEnabled(!localRuntimeEnabled)}
              />
            </SettingField>

            <AnimatePresence>
              {localRuntimeEnabled && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.25 }}
                  className="overflow-hidden"
                >
                  <SettingField
                    label="Ollama Base URL"
                    description="Upstream Ollama server address"
                  >
                    <TextInput
                      value={ollamaUrl}
                      onChange={setOllamaUrl}
                      placeholder="http://localhost:11434"
                      mono
                    />
                  </SettingField>
                </motion.div>
              )}
            </AnimatePresence>

            <SettingField
              label="Default Model"
              description="Fallback model when none is specified in the request"
            >
              <TextInput
                value={defaultModel}
                onChange={setDefaultModel}
                placeholder="deepseek-r1"
                mono
              />
            </SettingField>

            <SettingField
              label="CORS Origins"
              description="Comma-separated allowed origins (env-driven, restart required)"
            >
              <TextInput
                value={corsOrigins}
                onChange={setCorsOrigins}
                placeholder="http://localhost:5173"
                mono
              />
            </SettingField>
          </div>
        </GlassCard>

        {/* HomePilot */}
        <GlassCard delay={0.2}>
          <SectionTitle
            icon={Home}
            title="HomePilot"
            subtitle="Connect to HomePilot personas and personalities"
            color="#14b8a6"
            badge={hpEnabled ? { label: 'Enabled', color: '#14b8a6' } : undefined}
          />

          <div className="space-y-0">
            <SettingField
              label="Enable HomePilot"
              description="Register HomePilot as a backend node to expose personas as models"
            >
              <Toggle
                enabled={hpEnabled}
                onToggle={() => setHpEnabled(!hpEnabled)}
              />
            </SettingField>

            <AnimatePresence>
              {hpEnabled && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.25 }}
                  className="overflow-hidden"
                >
                  <SettingField
                    label="HomePilot URL"
                    description="Base URL of the HomePilot backend"
                  >
                    <TextInput
                      value={hpBaseUrl}
                      onChange={setHpBaseUrl}
                      placeholder="http://localhost:8000"
                      mono
                    />
                  </SettingField>

                  <SettingField
                    label="API Key"
                    description="HomePilot shared API key (leave empty if not required)"
                  >
                    <TextInput
                      value={hpApiKey}
                      onChange={setHpApiKey}
                      placeholder="my-secret"
                      type="password"
                    />
                  </SettingField>

                  <div className="py-3 text-xs text-white/30">
                    When enabled, persona and personality models from HomePilot
                    will appear in the Model Inventory and be routable via
                    <code className="text-white/50 mx-1">model="persona:&lt;id&gt;"</code>
                    or
                    <code className="text-white/50 mx-1">model="personality:&lt;id&gt;"</code>.
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </GlassCard>

        {/* Rate limits */}
        <RateLimitsSection delay={0.22} saveRef={saveRateLimits} />

        {/* Cloud Relay */}
        <GlassCard delay={0.25}>
          <SectionTitle
            icon={Server}
            title="Cloud Relay"
            subtitle="Link this gateway to OllaBridge Cloud for remote Quest VR access"
            color="#00e5ff"
          />
          <div className="py-3 text-xs text-white/30">
            Cloud relay settings are managed on the{' '}
            <span className="text-glow-cyan/70 font-medium">Cloud</span> page
            in the sidebar. Use it to pair this PC with OllaBridge Cloud, view connection
            status, and manage the WebSocket tunnel to your Quest VR headsets.
          </div>
        </GlassCard>

        {/* Save bar */}
        <div className="sticky bottom-0 pb-6 pt-2">
          <motion.div
            className="flex items-center justify-between px-5 py-3 rounded-2xl"
            style={{
              background:
                'linear-gradient(135deg, rgba(15,20,55,0.85), rgba(10,14,40,0.8))',
              backdropFilter: 'blur(20px)',
              border: '1px solid rgba(100,160,255,0.12)',
              boxShadow:
                '0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.04)',
            }}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
          >
            <div className="flex items-center gap-2 text-xs text-white/40">
              {error ? (
                <>
                  <AlertTriangle size={14} className="text-red-400" />
                  <span className="text-red-400">{error}</span>
                </>
              ) : (
                <>
                  <RefreshCw size={14} />
                  <span>
                    Changes apply instantly — backends are reconfigured live.
                  </span>
                </>
              )}
            </div>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-medium transition-all duration-200 disabled:opacity-50"
              style={{
                background: saved
                  ? 'linear-gradient(135deg, rgba(20,184,166,0.3), rgba(20,184,166,0.15))'
                  : 'linear-gradient(135deg, rgba(0,229,255,0.2), rgba(139,92,246,0.2))',
                border: saved
                  ? '1px solid rgba(20,184,166,0.4)'
                  : '1px solid rgba(0,229,255,0.3)',
                color: saved ? '#14b8a6' : '#00e5ff',
              }}
            >
              {saving ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  Saving...
                </>
              ) : saved ? (
                <>
                  <Check size={14} />
                  Saved — backends reconfigured
                </>
              ) : (
                <>
                  <Save size={14} />
                  Save Settings
                </>
              )}
            </button>
          </motion.div>
        </div>
      </div>
    </div>
  )
}
