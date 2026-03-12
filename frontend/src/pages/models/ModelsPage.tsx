import { motion, AnimatePresence } from 'framer-motion'
import {
  Brain,
  Home,
  Server,
  Settings,
  RefreshCw,
  AlertTriangle,
  Loader2,
  Search,
} from 'lucide-react'
import { useState } from 'react'
import { useModels, useRuntimes, useHealth, useSettings } from '../../lib/hooks'
import { api } from '../../lib/api'
import { useQueryClient } from '@tanstack/react-query'
import type { Page } from '../../App'

export function ModelsPage({ onNavigate }: { onNavigate: (page: Page) => void }) {
  const { data: health } = useHealth()
  const { data: modelsData, isLoading: modelsLoading } = useModels()
  const { data: runtimesData } = useRuntimes()
  const { data: settingsData } = useSettings()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const isOnline = health?.status === 'ok'
  const models = modelsData?.data ?? []
  const runtimes = runtimesData?.runtimes ?? []
  const localEnabled = settingsData?.local_runtime_enabled ?? true
  const hpEnabled = settingsData?.homepilot_enabled ?? false

  // Group models by source
  const hpModels = models.filter(
    (m) => m.owned_by === 'homepilot' || m.id?.startsWith('persona:')
  )
  const ollamaModels = models.filter(
    (m) => m.owned_by !== 'homepilot' && !m.id?.startsWith('persona:')
  )

  // Filter by search
  const filterModels = (list: typeof models) =>
    search
      ? list.filter((m) => m.id.toLowerCase().includes(search.toLowerCase()))
      : list

  const handleRefresh = async () => {
    setRefreshing(true)
    await queryClient.invalidateQueries({ queryKey: ['models'] })
    await queryClient.invalidateQueries({ queryKey: ['runtimes'] })
    setTimeout(() => setRefreshing(false), 800)
  }

  // Quick-enable backend
  const handleEnableBackend = async (backend: 'ollama' | 'homepilot') => {
    try {
      if (backend === 'ollama') {
        await api.updateSettings({ local_runtime_enabled: true })
      } else {
        await api.updateSettings({ homepilot_enabled: true })
      }
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      queryClient.invalidateQueries({ queryKey: ['health'] })
      queryClient.invalidateQueries({ queryKey: ['runtimes'] })
      queryClient.invalidateQueries({ queryKey: ['models'] })
    } catch {
      // Fall back to settings page for full configuration
      onNavigate('settings')
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">
        {/* Header bar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{
                background: 'linear-gradient(135deg, rgba(0,229,255,0.15), rgba(139,92,246,0.1))',
                border: '1px solid rgba(0,229,255,0.2)',
              }}
            >
              <Brain size={18} className="text-glow-cyan" />
            </div>
            <div>
              <h1 className="text-white/90 font-semibold text-lg">
                Model Inventory
              </h1>
              <p className="text-white/35 text-xs">
                {models.length} model{models.length !== 1 ? 's' : ''} available across {runtimes.length} runtime{runtimes.length !== 1 ? 's' : ''}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Search */}
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/25" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search models..."
                className="pl-9 pr-3 py-2 w-56 rounded-xl bg-white/5 border border-white/10 text-sm text-white/80 placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
              />
            </div>

            {/* Refresh */}
            <motion.button
              onClick={handleRefresh}
              className="p-2.5 rounded-xl bg-white/5 border border-white/10 text-white/40 hover:text-white/70 hover:border-white/20 transition-colors"
              whileTap={{ scale: 0.95 }}
            >
              <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
            </motion.button>

            {/* Settings link */}
            <motion.button
              onClick={() => onNavigate('settings')}
              className="p-2.5 rounded-xl bg-white/5 border border-white/10 text-white/40 hover:text-white/70 hover:border-white/20 transition-colors"
              whileTap={{ scale: 0.95 }}
            >
              <Settings size={16} />
            </motion.button>
          </div>
        </div>

        {/* Not online state */}
        {!isOnline && (
          <motion.div
            className="glass-card p-8 flex flex-col items-center gap-4 text-center"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <AlertTriangle size={32} className="text-amber-400/60" />
            <div>
              <h3 className="text-white/80 font-semibold mb-1">Gateway Offline</h3>
              <p className="text-white/40 text-sm max-w-md">
                No backends are connected. Enable a backend in{' '}
                <button
                  onClick={() => onNavigate('settings')}
                  className="text-glow-cyan hover:underline"
                >
                  Settings
                </button>{' '}
                to see available models.
              </p>
            </div>
          </motion.div>
        )}

        {/* Loading */}
        {isOnline && modelsLoading && (
          <div className="flex items-center justify-center py-16 gap-2 text-white/40 text-sm">
            <Loader2 size={16} className="animate-spin" />
            Loading models...
          </div>
        )}

        {/* Backend sections */}
        {isOnline && !modelsLoading && (
          <>
            {/* Ollama Section */}
            <BackendSection
              title="Ollama"
              icon={<Server size={16} />}
              color="#00e5ff"
              enabled={localEnabled}
              models={filterModels(ollamaModels)}
              emptyMessage={
                localEnabled
                  ? 'No Ollama models found. Pull models with: ollama pull <model-name>'
                  : undefined
              }
              onEnable={() => handleEnableBackend('ollama')}
              onConfigure={() => onNavigate('settings')}
            />

            {/* HomePilot Section */}
            <BackendSection
              title="HomePilot"
              icon={<Home size={16} />}
              color="#14b8a6"
              enabled={hpEnabled}
              models={filterModels(hpModels)}
              emptyMessage={
                hpEnabled
                  ? 'No HomePilot personas found. Check your HomePilot URL and API key in Settings.'
                  : undefined
              }
              onEnable={() => handleEnableBackend('homepilot')}
              onConfigure={() => onNavigate('settings')}
            />

            {/* Empty state when no models at all */}
            {models.length === 0 && localEnabled && (
              <motion.div
                className="glass-card p-8 flex flex-col items-center gap-4 text-center"
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <Brain size={32} className="text-white/20" />
                <div>
                  <h3 className="text-white/60 font-semibold mb-1">No Models Available</h3>
                  <p className="text-white/35 text-sm max-w-md">
                    Make sure your backends are running and properly configured.
                  </p>
                </div>
                <motion.button
                  onClick={() => onNavigate('settings')}
                  className="mt-2 px-5 py-2.5 rounded-xl text-sm font-medium"
                  style={{
                    background: 'linear-gradient(135deg, rgba(0,229,255,0.15), rgba(139,92,246,0.15))',
                    border: '1px solid rgba(0,229,255,0.25)',
                    color: '#00e5ff',
                  }}
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.97 }}
                >
                  Open Settings
                </motion.button>
              </motion.div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Sub-components ───────────────────────────────────────────────────────

function BackendSection({
  title,
  icon,
  color,
  enabled,
  models,
  emptyMessage,
  onEnable,
  onConfigure,
}: {
  title: string
  icon: React.ReactNode
  color: string
  enabled: boolean
  models: { id: string; owned_by?: string }[]
  emptyMessage?: string
  onEnable: () => void
  onConfigure: () => void
}) {
  return (
    <motion.div
      className="glass-card overflow-hidden"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
    >
      {/* Section header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{
              background: `${color}15`,
              border: `1px solid ${color}30`,
              color,
            }}
          >
            {icon}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-white/85 font-semibold text-sm">{title}</span>
              <span
                className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
                style={{
                  background: enabled ? `${color}15` : 'rgba(255,255,255,0.05)',
                  color: enabled ? color : 'rgba(255,255,255,0.3)',
                  border: `1px solid ${enabled ? color + '30' : 'rgba(255,255,255,0.08)'}`,
                }}
              >
                {enabled ? `${models.length} model${models.length !== 1 ? 's' : ''}` : 'Disabled'}
              </span>
            </div>
          </div>
        </div>

        <motion.button
          onClick={onConfigure}
          className="text-xs text-white/35 hover:text-white/60 transition-colors flex items-center gap-1"
          whileTap={{ scale: 0.95 }}
        >
          <Settings size={12} />
          Configure
        </motion.button>
      </div>

      {/* Content */}
      {!enabled ? (
        <div className="px-6 py-8 flex flex-col items-center gap-3 text-center">
          <p className="text-white/35 text-sm">
            {title} backend is not enabled.
          </p>
          <motion.button
            onClick={onEnable}
            className="px-4 py-2 rounded-xl text-sm font-medium"
            style={{
              background: `${color}12`,
              border: `1px solid ${color}25`,
              color,
            }}
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
          >
            Enable {title}
          </motion.button>
        </div>
      ) : models.length === 0 ? (
        <div className="px-6 py-8 text-center">
          <p className="text-white/35 text-sm">{emptyMessage}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-px bg-white/[0.04]">
          <AnimatePresence>
            {models.map((model, idx) => (
              <ModelCard
                key={model.id}
                model={model}
                color={color}
                delay={idx * 0.03}
              />
            ))}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  )
}

function ModelCard({
  model,
  color,
  delay,
}: {
  model: { id: string; owned_by?: string }
  color: string
  delay: number
}) {
  // Extract a clean display name
  const displayName = model.id.replace('persona:', '')
  const isPersona = model.id.startsWith('persona:')

  return (
    <motion.div
      className="px-5 py-4 bg-navy-900/50 hover:bg-white/[0.03] transition-colors"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay }}
    >
      <div className="flex items-center gap-3">
        <div
          className="w-2 h-2 rounded-full shrink-0"
          style={{
            background: `radial-gradient(circle, ${color} 30%, transparent 100%)`,
            boxShadow: `0 0 6px ${color}60`,
          }}
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-white/75 font-medium truncate font-mono">
            {displayName}
          </p>
          <p className="text-[10px] text-white/25 mt-0.5">
            {isPersona ? 'HomePilot Persona' : model.owned_by || 'ollama'}
          </p>
        </div>
      </div>
    </motion.div>
  )
}
