import { motion } from 'framer-motion'
import { useHealth, useModels, useRuntimes } from '../../lib/hooks'
import { TowerOrb } from './TowerOrb'
import { SignalBeams } from './SignalBeams'
import type { Page } from '../../App'

/** The central broadcast tower visualization — pipeline view with inputs → OllaBridge → outputs. */
export function TowerCanvas({ onNavigate }: { onNavigate: (page: Page) => void }) {
  const { data: health } = useHealth()
  const { data: modelsData } = useModels()
  const { data: runtimesData } = useRuntimes()

  const modelCount = modelsData?.data?.length ?? 0
  const runtimeCount = runtimesData?.count ?? 0
  const runtimes = runtimesData?.runtimes ?? []
  const isOnline = health?.status === 'ok'

  // Check if HomePilot is registered as a runtime
  const hpRuntime = runtimes.find(
    (rt) => rt.node_id === 'homepilot' || rt.tags.includes('homepilot')
  )
  const hpOnline = hpRuntime?.healthy ?? false

  return (
    <div className="absolute inset-0 flex items-center justify-center">
      {/* === SVG overlay for beams, tower structure, and ring === */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none"
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Tower vertical shaft */}
        <line
          x1="50" y1="52" x2="50" y2="68"
          stroke="url(#shaft-grad)"
          strokeWidth="0.3"
          vectorEffect="non-scaling-stroke"
        />
        <line
          x1="50" y1="52" x2="50" y2="68"
          stroke="#00e5ff"
          strokeWidth="2"
          strokeOpacity="0.06"
          filter="url(#beam-bloom)"
          vectorEffect="non-scaling-stroke"
        />

        <defs>
          <linearGradient id="shaft-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#00e5ff" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#00e5ff" stopOpacity="0.08" />
          </linearGradient>
        </defs>

        {/* Animated energy particles in the shaft */}
        {isOnline && (
          <>
            {[0, 1, 2].map((i) => (
              <circle key={`shaft-p-${i}`} r="0.6" fill="#00e5ff" filter="url(#beam-glow-sm)">
                <animate attributeName="cy" values="52;68" dur="1.5s" begin={`${i * 0.5}s`} repeatCount="indefinite" />
                <animate attributeName="cx" values="50;50" dur="1.5s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="1;0" dur="1.5s" begin={`${i * 0.5}s`} repeatCount="indefinite" />
              </circle>
            ))}
            <circle r="0.5" fill="#8b5cf6" filter="url(#beam-glow-sm)">
              <animate attributeName="cy" values="52;68" dur="1.5s" begin="0.75s" repeatCount="indefinite" />
              <animate attributeName="cx" values="50;50" dur="1.5s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.8;0" dur="1.5s" begin="0.75s" repeatCount="indefinite" />
            </circle>
          </>
        )}

        {/* Signal beams (fan out to consumer cards) */}
        <SignalBeams isOnline={isOnline} />
      </svg>

      {/* === HTML layer: tower structure === */}
      <div className="relative flex flex-col items-center" style={{ marginTop: '-6%' }}>
        {/* Source & Model chips row */}
        <div className="flex items-center justify-between mb-8" style={{ width: 820 }}>
          {/* Left: Input Sources */}
          <InputSourcesChip />
          <ConnectionDots />

          {/* Center spacer for orb */}
          <div className="w-40" />
          <ConnectionDots />

          {/* Right: LLM Sources (HomePilot + Ollama) */}
          <div className="flex items-center gap-3">
            <LLMSourceChip
              label="HomePilot"
              icon="home"
              color="#14b8a6"
              online={hpOnline}
              subtitle="Persona AI"
              onClick={() => onNavigate('settings')}
            />
            <LLMSourceChip
              label="Ollama"
              icon="brain"
              color="#00e5ff"
              online={isOnline}
              count={modelCount}
              subtitle={`${modelCount} model${modelCount !== 1 ? 's' : ''}`}
              onClick={() => onNavigate('models')}
            />
          </div>
        </div>

        {/* Main Orb */}
        <TowerOrb isOnline={isOnline} defaultModel={health?.default_model} />

        {/* Tower column */}
        <div className="relative w-px" style={{ height: 140 }}>
          <div
            className="absolute left-1/2 -translate-x-1/2 w-16 h-full pointer-events-none"
            style={{
              background: isOnline
                ? 'linear-gradient(180deg, rgba(0,229,255,0.08), transparent)'
                : 'none',
              filter: 'blur(12px)',
            }}
          />
        </div>

        {/* Tower base platform */}
        <div className="relative">
          {isOnline && (
            <div
              className="absolute left-1/2 -translate-x-1/2 -top-4 w-48 h-12 pointer-events-none"
              style={{
                background: 'radial-gradient(ellipse, rgba(0,229,255,0.12), transparent 70%)',
                filter: 'blur(16px)',
              }}
            />
          )}

          <motion.div
            className="w-48 h-10 rounded-[50%]"
            style={{
              border: '1px solid rgba(0,229,255,0.2)',
              background: 'radial-gradient(ellipse, rgba(0,229,255,0.08) 0%, transparent 70%)',
            }}
            animate={isOnline ? { opacity: [0.5, 1, 0.5] } : {}}
            transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
          />

          <motion.span
            className="absolute -right-16 top-1/2 -translate-y-1/2 text-sm text-white/30 font-medium tracking-widest"
            animate={{ opacity: [0.3, 0.6, 0.3] }}
            transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
          >
            tower
          </motion.span>
        </div>

        {/* Runtime count */}
        <div className="mt-3 text-[11px] text-white/20 uppercase tracking-[0.2em] font-medium">
          {runtimeCount} runtime{runtimeCount !== 1 ? 's' : ''} connected
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ───────────────────────────────────────────────────────

/** Input sources chip — shows available input types feeding into OllaBridge. */
function InputSourcesChip() {
  const inputs = [
    { label: 'API', color: '#00e5ff' },
    { label: 'RSS', color: '#f59e0b' },
    { label: 'Docs', color: '#8b5cf6' },
    { label: 'Manual', color: '#6366f1' },
  ]

  return (
    <motion.div
      className="flex items-center gap-2.5 px-4 py-3 cursor-pointer"
      style={{
        background: 'linear-gradient(135deg, rgba(15,22,60,0.7), rgba(8,12,35,0.5))',
        backdropFilter: 'blur(14px)',
        border: '1px solid rgba(0,229,255,0.12)',
        borderRadius: 14,
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 0 20px rgba(0,229,255,0.04), 0 4px 20px rgba(0,0,0,0.3)',
      }}
      whileHover={{
        scale: 1.04,
        borderColor: 'rgba(0,229,255,0.3)',
      }}
    >
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center"
        style={{
          background: 'rgba(0,229,255,0.08)',
          border: '1px solid rgba(0,229,255,0.2)',
        }}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-glow-cyan">
          <polyline points="22,12 16,12 14,15 10,15 8,12 2,12" />
          <path d="M5.45,5.11 2,12v6a2,2 0 0,0 2,2h16a2,2 0 0,0 2-2V12L18.55,5.11A2,2 0 0,0 16.76,4H7.24A2,2 0 0,0 5.45,5.11Z" />
        </svg>
      </div>

      <div>
        <div className="text-sm font-semibold text-white/85">Source Inputs</div>
        <div className="flex gap-1.5 mt-1">
          {inputs.map((inp) => (
            <span
              key={inp.label}
              className="px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider"
              style={{
                background: `${inp.color}15`,
                color: `${inp.color}cc`,
                border: `1px solid ${inp.color}25`,
              }}
            >
              {inp.label}
            </span>
          ))}
        </div>
      </div>
    </motion.div>
  )
}

/** LLM source chip — represents an LLM backend (HomePilot or Ollama). */
function LLMSourceChip({
  label,
  icon,
  color,
  online,
  count,
  subtitle,
  onClick,
}: {
  label: string
  icon: string
  color: string
  online: boolean
  count?: number
  subtitle?: string
  onClick?: () => void
}) {
  return (
    <motion.div
      className="flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors"
      style={{
        background: 'linear-gradient(135deg, rgba(15,22,60,0.7), rgba(8,12,35,0.5))',
        backdropFilter: 'blur(14px)',
        border: `1px solid ${online ? color + '25' : 'rgba(255,255,255,0.08)'}`,
        borderRadius: 14,
        boxShadow: online
          ? `inset 0 1px 0 rgba(255,255,255,0.04), 0 0 20px ${color}10, 0 4px 20px rgba(0,0,0,0.3)`
          : 'inset 0 1px 0 rgba(255,255,255,0.04), 0 4px 20px rgba(0,0,0,0.3)',
      }}
      whileHover={{
        scale: 1.04,
        borderColor: color + '40',
      }}
      whileTap={{ scale: 0.97 }}
      onClick={onClick}
    >
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center"
        style={{
          background: `${color}12`,
          border: `1px solid ${color}30`,
        }}
      >
        {icon === 'home' ? (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color }}>
            <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
            <polyline points="9 22 9 12 15 12 15 22" />
          </svg>
        ) : (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color }}>
            <path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z" />
            <line x1="9" y1="21" x2="15" y2="21" />
          </svg>
        )}
      </div>

      <div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-white/85">{label}</span>
          <motion.div
            className="w-2 h-2 rounded-full"
            style={{
              background: online
                ? `radial-gradient(circle, ${color} 25%, ${color}66 55%, transparent 100%)`
                : 'radial-gradient(circle, rgba(255,255,255,0.15) 25%, transparent 70%)',
              boxShadow: online ? `0 0 6px ${color}80` : 'none',
            }}
            animate={online ? { opacity: [0.6, 1, 0.6] } : {}}
            transition={{ duration: 2, repeat: Infinity }}
          />
        </div>
        <div className="text-[10px] text-white/35">
          {subtitle || (count !== undefined ? `${count} available` : '')}
        </div>
      </div>
    </motion.div>
  )
}

function ConnectionDots() {
  return (
    <div className="flex items-center gap-2">
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          className="w-2 h-2 rounded-full"
          style={{
            background: 'radial-gradient(circle, rgba(0,229,255,0.6) 20%, rgba(0,229,255,0.2) 50%, transparent 100%)',
            boxShadow: '0 0 4px rgba(0,229,255,0.3)',
          }}
          animate={{ opacity: [0.25, 0.8, 0.25] }}
          transition={{ duration: 1.5, repeat: Infinity, delay: i * 0.3 }}
        />
      ))}
    </div>
  )
}
