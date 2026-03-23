import { motion } from 'framer-motion'
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
    { label: 'Status', value: isOnline ? 'Online' : 'Offline', color: isOnline ? '#14b8a6' : '#ec4899', dot: true },
    { label: 'Cloud', value: cloudLabel, color: cloudColor, dot: cloudConnected },
    { label: 'Source Mode', value: sourceMode === 'none' ? '—' : sourceMode[0].toUpperCase() + sourceMode.slice(1), color: '#68f4ff' },
    { label: 'Models', value: String(modelCount), color: '#68f4ff' },
    { label: 'Runtimes', value: String(runtimeCount), color: '#8b5cf6' },
    { label: 'Consumers', value: String(consumerCount), color: '#f59e0b' },
    { label: 'Flow', value: flow?.active ? `${flow.requests_8s} active` : 'Idle', color: flow?.active ? '#68f4ff' : 'rgba(255,255,255,0.5)' },
    { label: 'Est tok/min', value: String(flow?.est_total_tokens_1m ?? 0), color: '#14b8a6' },
  ]

  return (
    <div className="absolute top-4 right-4 flex flex-col gap-2 z-10">
      {badges.map((badge, i) => (
        <motion.div
          key={badge.label}
          className="flex items-center gap-2.5 px-3.5 py-2 text-xs"
          style={{
            background: 'linear-gradient(135deg, rgba(12,16,45,0.68), rgba(8,10,30,0.52))',
            backdropFilter: 'blur(12px)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 10,
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.03)',
            minWidth: 148,
          }}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.05 * i, duration: 0.3 }}
        >
          {badge.dot && (
            <motion.div className="w-2 h-2 rounded-full" style={{ backgroundColor: badge.color, boxShadow: `0 0 6px ${badge.color}80` }} animate={isOnline ? { scale: [1, 1.3, 1] } : {}} transition={{ duration: 1.5, repeat: Infinity }} />
          )}
          <span className="text-white/35 font-medium">{badge.label}</span>
          <span className="ml-auto font-bold" style={{ color: badge.color }}>{badge.value}</span>
        </motion.div>
      ))}
    </div>
  )
}
