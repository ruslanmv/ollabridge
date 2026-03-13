import { motion } from 'framer-motion'
import { useHealth, useModels, useRuntimes, useRecent } from '../../lib/hooks'

/** Heads-up display overlay — top-right badges with live metrics. */
export function StatusHud() {
  const { data: health } = useHealth()
  const { data: modelsData } = useModels()
  const { data: runtimesData } = useRuntimes()
  const { data: recentData } = useRecent(5)

  const isOnline = health?.status === 'ok'
  const modelCount = modelsData?.data?.length ?? 0
  const runtimeCount = runtimesData?.count ?? 0
  const recentCount = recentData?.requests?.length ?? 0

  const badges = [
    {
      label: 'Status',
      value: isOnline ? 'Online' : 'Offline',
      color: isOnline ? '#14b8a6' : '#ec4899',
      dot: true,
    },
    { label: 'Mode', value: health?.mode ?? '\u2014', color: 'rgba(255,255,255,0.55)' },
    { label: 'Models', value: String(modelCount), color: '#00e5ff' },
    { label: 'Runtimes', value: String(runtimeCount), color: '#8b5cf6' },
    { label: 'Recent', value: String(recentCount), color: '#f59e0b' },
  ]

  return (
    <div className="absolute top-4 right-4 flex flex-col gap-2 z-10">
      {badges.map((badge, i) => (
        <motion.div
          key={badge.label}
          className="flex items-center gap-2.5 px-3.5 py-2 text-xs"
          style={{
            background: 'linear-gradient(135deg, rgba(12,16,45,0.65), rgba(8,10,30,0.5))',
            backdropFilter: 'blur(12px)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 10,
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.03)',
            minWidth: 130,
          }}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.05 * i, duration: 0.3 }}
        >
          {badge.dot && (
            <motion.div
              className="w-2 h-2 rounded-full"
              style={{
                backgroundColor: badge.color,
                boxShadow: `0 0 6px ${badge.color}80`,
              }}
              animate={isOnline ? { scale: [1, 1.3, 1] } : {}}
              transition={{ duration: 1.5, repeat: Infinity }}
            />
          )}
          <span className="text-white/35 font-medium">{badge.label}</span>
          <span className="ml-auto font-bold" style={{ color: badge.color }}>
            {badge.value}
          </span>
        </motion.div>
      ))}
    </div>
  )
}
