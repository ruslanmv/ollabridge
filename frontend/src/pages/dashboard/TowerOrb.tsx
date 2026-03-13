import { motion } from 'framer-motion'

interface TowerOrbProps {
  isOnline: boolean
  defaultModel?: string
  activeFlow?: boolean
}

export function TowerOrb({ isOnline, defaultModel, activeFlow = false }: TowerOrbProps) {
  return (
    <div className="relative flex items-center justify-center" style={{ width: 320, height: 320 }}>
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          width: 470,
          height: 470,
          background: isOnline
            ? 'radial-gradient(circle, rgba(0,229,255,0.18), rgba(139,92,246,0.09) 50%, transparent 72%)'
            : 'radial-gradient(circle, rgba(239,68,68,0.1), transparent 72%)',
          filter: 'blur(70px)',
        }}
        animate={{ scale: activeFlow ? [1, 1.16, 1] : [1, 1.06, 1], opacity: activeFlow ? [0.55, 0.9, 0.55] : [0.35, 0.55, 0.35] }}
        transition={{ duration: activeFlow ? 2.2 : 5, repeat: Infinity, ease: 'easeInOut' }}
      />

      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{ width: 250, height: 250, border: isOnline ? '1px solid rgba(0,229,255,0.16)' : '1px solid rgba(239,68,68,0.12)' }}
        animate={{ rotate: 360 }}
        transition={{ duration: 40, repeat: Infinity, ease: 'linear' }}
      />
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{ width: 230, height: 230, border: '1px solid rgba(139,92,246,0.1)' }}
        animate={{ rotate: -360 }}
        transition={{ duration: 52, repeat: Infinity, ease: 'linear' }}
      />

      <motion.div
        className="relative rounded-full overflow-hidden flex flex-col items-center justify-center"
        style={{
          width: 190,
          height: 190,
          background: isOnline
            ? 'radial-gradient(circle at 50% 18%, rgba(196,247,255,0.28), rgba(0,229,255,0.18) 22%, rgba(139,92,246,0.18) 55%, rgba(8,10,25,0.96) 100%)'
            : 'radial-gradient(circle at 50% 18%, rgba(255,220,220,0.12), rgba(8,10,25,0.96) 100%)',
          border: isOnline ? '1.6px solid rgba(130,247,255,0.35)' : '1px solid rgba(239,68,68,0.22)',
          boxShadow: isOnline
            ? '0 0 55px rgba(0,229,255,0.26), inset 0 0 40px rgba(0,229,255,0.1), inset 0 -40px 70px rgba(139,92,246,0.18)'
            : '0 0 20px rgba(239,68,68,0.12)',
        }}
        animate={{ scale: activeFlow ? [1, 1.03, 1] : [1, 1.012, 1] }}
        transition={{ duration: activeFlow ? 2.2 : 4.5, repeat: Infinity, ease: 'easeInOut' }}
      >
        <div className="absolute inset-x-0 top-0 h-[35%]" style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.12), transparent)' }} />
        {isOnline && (
          <div className="absolute inset-0 overflow-hidden rounded-full opacity-25 pointer-events-none">
            {[0,1,2,3,4,5].map((i) => (
              <motion.div
                key={i}
                className="absolute w-px bg-gradient-to-b from-glow-cyan to-transparent"
                style={{ left: `${24 + i * 10}%`, height: '72%' }}
                animate={{ y: activeFlow ? ['-25%', '130%'] : ['-10%', '90%'] }}
                transition={{ duration: activeFlow ? 1.5 + i * 0.18 : 4 + i * 0.2, repeat: Infinity, ease: 'linear', delay: i * 0.25 }}
              />
            ))}
          </div>
        )}

        <span className="relative z-10 font-bold tracking-[0.28em] uppercase" style={{ fontSize: 12, color: 'rgba(255,255,255,0.52)' }}>OLLABRIDGE</span>
        <span className="relative z-10 font-semibold mt-1" style={{ fontSize: 16, color: isOnline ? '#6ff5ff' : '#ef4444', textShadow: isOnline ? '0 0 12px rgba(0,229,255,0.65), 0 0 32px rgba(0,229,255,0.22)' : '0 0 8px rgba(239,68,68,0.4)' }}>{isOnline ? 'LLM CORE' : 'OFFLINE'}</span>
        {defaultModel && isOnline && <span className="relative z-10 mt-1 max-w-[120px] truncate text-[10px] text-white/20">{defaultModel}</span>}

        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-full h-[28%]" style={{ background: isOnline ? 'radial-gradient(ellipse at 50% 100%, rgba(255,255,255,0.14), rgba(139,92,246,0.16), transparent 70%)' : 'none' }} />
      </motion.div>

      {isOnline && [0,1,2,3,4,5].map((i) => (
        <motion.div
          key={`orb-particle-${i}`}
          className="absolute rounded-full pointer-events-none"
          style={{
            width: i % 2 === 0 ? 6 : 4,
            height: i % 2 === 0 ? 6 : 4,
            background: i % 2 === 0 ? '#68f4ff' : '#a87aff',
            boxShadow: i % 2 === 0 ? '0 0 8px rgba(104,244,255,0.8)' : '0 0 6px rgba(168,122,255,0.8)',
          }}
          animate={{
            x: [Math.cos((i * Math.PI) / 3) * 118, Math.cos((i * Math.PI) / 3 + 1) * 126, Math.cos((i * Math.PI) / 3) * 118],
            y: [Math.sin((i * Math.PI) / 3) * 118, Math.sin((i * Math.PI) / 3 + 1) * 126, Math.sin((i * Math.PI) / 3) * 118],
            opacity: activeFlow ? [0.3, 0.95, 0.3] : [0.18, 0.45, 0.18],
          }}
          transition={{ duration: activeFlow ? 3.8 + i * 0.25 : 8 + i * 0.35, repeat: Infinity, ease: 'easeInOut', delay: i * 0.3 }}
        />
      ))}
    </div>
  )
}
