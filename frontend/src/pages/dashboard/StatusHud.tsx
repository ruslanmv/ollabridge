import { motion } from 'framer-motion'
import {
  Activity,
  AudioWaveform,
  Box,
  Clock4,
  Cloud,
  Gauge,
  Server,
  Users,
} from 'lucide-react'
import { deriveSourceMode } from '../../lib/api'
import { useCloudStatus, useConsumerNodes, useFlowMetrics, useHealth, useModels, useRuntimes, useSettings } from '../../lib/hooks'

export function StatusHud() {
  const { data: health } = useHealth()
  const { data: settings } = useSettings()
  const { data: modelsData } = useModels()
  const { data: runtimesData } = useRuntimes()
  const { data: consumersData } = useConsumerNodes()
  const { data: flow } = useFlowMetrics()
  const { data: cloud } = useCloudStatus()

  const isOnline = health?.status === 'ok'
  const sourceMode = deriveSourceMode(settings)
  const modelCount = modelsData?.data?.length ?? 0
  const runtimeCount = runtimesData?.count ?? 0
  const consumerCount = consumersData?.count ?? 0

  const cloudConnected = cloud?.state === 'connected'
  const cloudLabel = cloud?.state === 'connected' ? `${cloud.models_count} models` : cloud?.state ?? 'Off'
  const cloudColor = cloudConnected ? '#14b8a6' : cloud?.state === 'reconnecting' ? '#f59e0b' : 'rgba(255,255,255,0.35)'

  const badges = [
    { label: 'Status', value: isOnline ? 'Online' : 'Offline', color: isOnline ? '#14b8a6' : '#ec4899', icon: Gauge, dot: true },
    { label: 'Cloud', value: cloudLabel, color: cloudColor, icon: Cloud, dot: cloudConnected },
    { label: 'Source Mode', value: sourceMode === 'none' ? '—' : sourceMode[0].toUpperCase() + sourceMode.slice(1), color: '#68f4ff', icon: Server },
    { label: 'Models', value: String(modelCount), color: '#68f4ff', icon: Box },
    { label: 'Runtimes', value: String(runtimeCount), color: '#8b5cf6', icon: Clock4 },
    { label: 'Consumers', value: String(consumerCount), color: '#f59e0b', icon: Users },
    { label: 'Flow', value: flow?.active ? `${flow.requests_8s} active` : 'Idle', color: flow?.active ? '#68f4ff' : 'rgba(255,255,255,0.5)', icon: Activity },
    { label: 'Est tok/min', value: String(flow?.est_total_tokens_1m ?? 0), color: '#14b8a6', icon: AudioWaveform },
  ]

  return (
    <div className="absolute top-5 right-5 flex flex-col gap-2.5 z-10">
      {badges.map((badge, i) => {
        const Icon = badge.icon
        return (
          <motion.div
            key={badge.label}
            className="flex items-center gap-3 px-3 py-2.5 text-xs"
            style={{
              background: 'linear-gradient(135deg, rgba(12,16,45,0.78), rgba(8,10,30,0.62))',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(255,255,255,0.07)',
              borderRadius: 14,
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 4px 16px rgba(0,0,0,0.25)',
              minWidth: 168,
            }}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.05 * i, duration: 0.3 }}
          >
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
              style={{ background: `${badge.color}14`, border: `1px solid ${badge.color}26` }}
            >
              {badge.dot ? (
                <motion.div
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ backgroundColor: badge.color, boxShadow: `0 0 8px ${badge.color}90` }}
                  animate={isOnline ? { scale: [1, 1.25, 1] } : {}}
                  transition={{ duration: 1.5, repeat: Infinity }}
                />
              ) : (
                <Icon size={15} style={{ color: badge.color }} />
              )}
            </div>
            <div className="min-w-0 flex flex-col gap-0.5">
              <span className="text-white/40 font-medium leading-none">{badge.label}</span>
              <span className="font-bold text-[13px] leading-none" style={{ color: badge.color }}>{badge.value}</span>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}
