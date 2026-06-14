import { motion } from 'framer-motion'
import { Cloud as CloudIcon, FileText, Layers, Plug } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useCloudStatus, useFlowMetrics, useHealth, useModels, useRuntimes, useSources } from '../../lib/hooks'
import { TowerOrb } from './TowerOrb'
import { SignalBeams } from './SignalBeams'
import type { Page } from '../../App'

function countStandardModels(ids: string[]) {
  return ids.filter((id) => !id.startsWith('persona:') && !id.startsWith('personality:')).length
}

export function TowerCanvas({ onNavigate }: { onNavigate: (page: Page) => void }) {
  const { data: health } = useHealth()
  const { data: modelsData } = useModels()
  const { data: runtimesData } = useRuntimes()
  const { data: flow } = useFlowMetrics()
  const { data: cloud } = useCloudStatus()
  const { data: sourcesData } = useSources()

  const isOnline = health?.status === 'ok'
  const cloudConnected = cloud?.state === 'connected'
  const cloudLabel = cloud?.state === 'connected' ? `${cloud.models_count} model${cloud.models_count !== 1 ? 's' : ''} shared` : cloud?.state === 'pairing' ? 'Pairing...' : 'Not linked'
  const models = modelsData?.data ?? []
  const standardCount = countStandardModels(models.map((m) => m.id))
  const runtimeCount = runtimesData?.count ?? 0
  const isFlowing = !!flow?.active && (flow?.requests_8s ?? 0) > 0
  const pulseCount = Math.max(1, Math.min(5, flow?.requests_8s ?? 1))
  const providerCount = sourcesData?.configured?.filter((s) => s.key_configured && s.enabled).length ?? 0

  return (
    <div className="absolute inset-0">
      <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 100 100" preserveAspectRatio="none">
        <defs>
          <linearGradient id="shaft-grad-v6" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#d4ffff" stopOpacity="0.5" />
            <stop offset="20%" stopColor="#78f7ff" stopOpacity="0.34" />
            <stop offset="100%" stopColor="#00e5ff" stopOpacity="0.02" />
          </linearGradient>
          <filter id="shaft-bloom-v6"><feGaussianBlur stdDeviation="6" /></filter>
          <filter id="shaft-dot-glow-v6"><feGaussianBlur stdDeviation="1.3" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>

        <ellipse cx="50" cy="60" rx="2.4" ry="0.8" fill="rgba(255,255,255,0.35)" opacity={isFlowing ? 0.85 : 0.25} filter="url(#shaft-bloom-v6)" />
        <rect x="47" y="38" width="6" height="24" fill="url(#shaft-grad-v6)" opacity={isOnline ? (isFlowing ? 0.35 : 0.12) : 0.04} filter="url(#shaft-bloom-v6)" rx="3" />
        <line x1="50" y1="39" x2="50" y2="61" stroke="#7df6ff" strokeOpacity={isFlowing ? '0.35' : '0.12'} strokeWidth="0.45" vectorEffect="non-scaling-stroke" />

        {isFlowing && Array.from({ length: pulseCount }).map((_, i) => (
          <g key={`shaft-pulse-${i}`}>
            <circle r="0.34" fill="#77f5ff" filter="url(#shaft-dot-glow-v6)">
              <animate attributeName="cy" values="40;60" dur="1.55s" begin={`${i * 0.26}s`} repeatCount="indefinite" />
              <animate attributeName="cx" values="50;50" dur="1.55s" begin={`${i * 0.26}s`} repeatCount="indefinite" />
              <animate attributeName="opacity" values="0;1;0" dur="1.55s" begin={`${i * 0.26}s`} repeatCount="indefinite" />
            </circle>
          </g>
        ))}

        <SignalBeams isOnline={isOnline} isFlowing={isFlowing} pulseCount={pulseCount} />
      </svg>

      {/* Flow layout (not centered-overflow) so the top cards can never be
          clipped under the header on short viewports. */}
      <div className="relative h-full w-full flex flex-col items-center px-6 pt-5 pb-2 min-h-0">
        {/* Top: source / provider / model cards */}
        <div className="flex items-center justify-center shrink-0 max-w-full">
          <SourceChip icon={FileText} label="Runtimes" subtitle="Ollama · HomePilot" color="#68f4ff" dotColor="#22c55e" onClick={() => onNavigate('runtimes')} />
          <ConnectionDots active={isFlowing} />
          <SourceChip
            icon={Plug}
            label="Sources"
            subtitle={providerCount > 0 ? `${providerCount} connected` : 'Disabled'}
            color="#8b5cf6"
            dim={providerCount === 0}
            dotColor={providerCount > 0 ? '#22c55e' : 'rgba(255,255,255,0.25)'}
            onClick={() => onNavigate('sources')}
          />
          <ConnectionDots active={isFlowing} />
          <SourceChip
            icon={Layers}
            label="Models"
            subtitle={standardCount > 0 ? `${standardCount} standard model${standardCount !== 1 ? 's' : ''}` : 'No models'}
            color="#68f4ff"
            dim={standardCount === 0}
            dotColor={standardCount > 0 ? '#22c55e' : 'rgba(255,255,255,0.25)'}
            onClick={() => onNavigate('models')}
          />
        </div>

        {/* Middle: orb + routing label + landing ring (flexes, never pushes
            the top cards out of view) */}
        <div className="flex-1 min-h-0 flex flex-col items-center justify-center">
          <div className="scale-90 xl:scale-100 origin-center">
            <TowerOrb isOnline={isOnline} defaultModel={health?.default_model} activeFlow={isFlowing} />
          </div>

          <div className="relative w-px h-8 xl:h-14">
            {isFlowing && (
              <motion.div
                className="absolute left-1/2 -translate-x-1/2 w-16 h-full pointer-events-none"
                style={{ background: 'linear-gradient(180deg, rgba(0,229,255,0.09), transparent)', filter: 'blur(12px)' }}
                animate={{ opacity: [0.45, 0.9, 0.45] }}
                transition={{ duration: 1.8, repeat: Infinity }}
              />
            )}
          </div>

          <div className="text-center mb-3">
            <div className="text-[12px] text-white/55 uppercase tracking-[0.3em] font-semibold">
              {isFlowing ? 'Live flow' : 'Model routing'}
            </div>
            <div className="mt-1 text-[11px] text-white/30 uppercase tracking-[0.22em] font-medium">
              {isFlowing
                ? `${flow?.requests_8s ?? 0} request${(flow?.requests_8s ?? 0) !== 1 ? 's' : ''} in 8s`
                : `${runtimeCount} runtime${runtimeCount !== 1 ? 's' : ''} connected`}
            </div>
          </div>

          <motion.div
            className="w-52 h-9 rounded-[50%]"
            style={{
              border: '1px solid rgba(0,229,255,0.18)',
              background: 'radial-gradient(ellipse, rgba(0,229,255,0.08) 0%, transparent 70%)',
              boxShadow: isFlowing ? '0 0 28px rgba(0,229,255,0.1)' : 'none',
            }}
            animate={isOnline ? { opacity: isFlowing ? [0.45, 0.95, 0.45] : [0.28, 0.5, 0.28] } : { opacity: 0.2 }}
            transition={{ duration: isFlowing ? 2.2 : 5, repeat: Infinity, ease: 'easeInOut' }}
          />
        </div>

        {/* Bottom: cloud relay entry point */}
        <div className="shrink-0 pb-1">
          <SourceChip
            icon={CloudIcon}
            label="Cloud Relay"
            subtitle={cloudLabel}
            color={cloudConnected ? '#14b8a6' : '#8b5cf6'}
            dim={!cloudConnected}
            dotColor={cloudConnected ? '#22c55e' : 'rgba(255,255,255,0.25)'}
            onClick={() => onNavigate('cloud')}
          />
        </div>
      </div>
    </div>
  )
}


function SourceChip({ icon: Icon, label, subtitle, color, dim = false, dotColor, onClick }: { icon: LucideIcon; label: string; subtitle: string; color: string; dim?: boolean; dotColor?: string; onClick: () => void }) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      className="group relative flex items-center gap-3 px-4 py-3 rounded-2xl text-left"
      style={{
        background: dim ? 'linear-gradient(135deg, rgba(12,16,45,0.52), rgba(8,10,30,0.42))' : 'linear-gradient(135deg, rgba(12,16,45,0.72), rgba(8,10,30,0.55))',
        border: `1px solid ${dim ? 'rgba(255,255,255,0.06)' : color + '44'}`,
        boxShadow: dim ? 'inset 0 1px 0 rgba(255,255,255,0.02)' : `0 0 30px ${color}12, inset 0 1px 0 rgba(255,255,255,0.03)`,
        minWidth: 200,
      }}
      whileHover={{ y: -2, scale: 1.01 }}
      whileTap={{ scale: 0.99 }}
    >
      {dotColor && (
        <span
          className="absolute top-2.5 right-3 w-2 h-2 rounded-full"
          style={{ background: dotColor, boxShadow: dotColor.startsWith('#') ? `0 0 8px ${dotColor}aa` : 'none' }}
        />
      )}
      <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: `${color}16`, border: `1px solid ${color}30` }}>
        <Icon size={16} style={{ color: dim ? 'rgba(255,255,255,0.3)' : color }} />
      </div>
      <div className="min-w-0">
        <div className="text-[12px] font-bold uppercase tracking-[0.14em] leading-tight" style={{ color: dim ? 'rgba(255,255,255,0.45)' : color }}>{label}</div>
        <div className="text-[12px] text-white/45 truncate mt-1">{subtitle}</div>
      </div>
    </motion.button>
  )
}

function ConnectionDots({ active }: { active: boolean }) {
  return (
    <div className="hidden md:flex items-center gap-2 px-5">
      {[0,1,2].map((i) => (
        <motion.div key={i} className="w-1.5 h-1.5 rounded-full" style={{ background: active ? '#68f4ff' : 'rgba(255,255,255,0.18)', boxShadow: active ? '0 0 8px rgba(104,244,255,0.6)' : 'none' }} animate={active ? { opacity: [0.25, 1, 0.25] } : { opacity: 0.45 }} transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.18 }} />
      ))}
    </div>
  )
}
