import { motion } from 'framer-motion'

interface TowerOrbProps {
  isOnline: boolean
  defaultModel?: string
}

/**
 * Multi-layer energy sphere — the "brain" of the broadcast tower.
 * Layers: bloom → halo → glass rings → core → highlight caps → digital rain → particles → label
 */
export function TowerOrb({ isOnline, defaultModel }: TowerOrbProps) {
  return (
    <div className="relative flex items-center justify-center" style={{ width: 260, height: 260 }}>
      {/* === Bloom layer (large soft atmospheric light) === */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          width: 400,
          height: 400,
          background: isOnline
            ? 'radial-gradient(circle, rgba(0,229,255,0.18), rgba(139,92,246,0.08) 50%, transparent 70%)'
            : 'radial-gradient(circle, rgba(239,68,68,0.08), transparent 70%)',
          filter: 'blur(50px)',
        }}
        animate={{ scale: [1, 1.12, 1], opacity: [0.5, 0.8, 0.5] }}
        transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
      />

      {/* === Outer glow halo === */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          width: 240,
          height: 240,
          background: isOnline
            ? 'radial-gradient(circle, rgba(0,229,255,0.1) 40%, transparent 70%)'
            : 'radial-gradient(circle, rgba(239,68,68,0.06) 40%, transparent 70%)',
        }}
        animate={{ scale: [1, 1.08, 1] }}
        transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
      />

      {/* === Glass edge ring (orbiting) === */}
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 200,
          height: 200,
          border: isOnline ? '1px solid rgba(0,229,255,0.15)' : '1px solid rgba(239,68,68,0.1)',
        }}
        animate={{ rotate: 360 }}
        transition={{ duration: 25, repeat: Infinity, ease: 'linear' }}
      >
        <motion.div
          className="absolute -top-1 left-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full"
          style={{
            background: isOnline
              ? 'radial-gradient(circle, #00e5ff 30%, rgba(0,229,255,0.4) 60%, transparent 100%)'
              : 'radial-gradient(circle, #ef4444 30%, rgba(239,68,68,0.4) 60%, transparent 100%)',
            boxShadow: isOnline
              ? '0 0 8px rgba(0,229,255,0.8), 0 0 20px rgba(0,229,255,0.4)'
              : '0 0 8px rgba(239,68,68,0.6)',
          }}
        />
      </motion.div>

      {/* === Second ring (counter-rotating) === */}
      {isOnline && (
        <motion.div
          className="absolute rounded-full"
          style={{
            width: 185,
            height: 185,
            border: '1px solid rgba(139,92,246,0.1)',
          }}
          animate={{ rotate: -360 }}
          transition={{ duration: 35, repeat: Infinity, ease: 'linear' }}
        >
          <motion.div
            className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 w-2 h-2 rounded-full"
            style={{
              background: 'radial-gradient(circle, #8b5cf6 30%, rgba(139,92,246,0.4) 60%, transparent 100%)',
              boxShadow: '0 0 6px rgba(139,92,246,0.8)',
            }}
          />
        </motion.div>
      )}

      {/* === Core sphere === */}
      <motion.div
        className="relative rounded-full flex flex-col items-center justify-center overflow-hidden"
        style={{
          width: 155,
          height: 155,
          background: isOnline
            ? 'radial-gradient(circle at 40% 30%, rgba(0,229,255,0.22), rgba(139,92,246,0.15) 50%, rgba(8,10,25,0.95) 100%)'
            : 'radial-gradient(circle at 40% 30%, rgba(239,68,68,0.12), rgba(8,10,25,0.95))',
          border: isOnline ? '1.5px solid rgba(0,229,255,0.3)' : '1px solid rgba(239,68,68,0.2)',
          boxShadow: isOnline
            ? '0 0 40px rgba(0,229,255,0.25), 0 0 80px rgba(0,229,255,0.1), inset 0 0 40px rgba(0,229,255,0.08)'
            : '0 0 20px rgba(239,68,68,0.1)',
        }}
        animate={isOnline ? { scale: [1, 1.02, 1] } : {}}
        transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut' }}
      >
        {/* Top highlight cap */}
        <div
          className="absolute top-0 left-1/2 -translate-x-1/2 w-[80%] h-[40%] rounded-b-full pointer-events-none"
          style={{
            background: isOnline
              ? 'linear-gradient(180deg, rgba(200,230,255,0.12) 0%, transparent 100%)'
              : 'linear-gradient(180deg, rgba(200,200,200,0.04) 0%, transparent 100%)',
          }}
        />

        {/* Digital rain (vertical animated lines inside core) */}
        {isOnline && (
          <div className="absolute inset-0 overflow-hidden rounded-full opacity-25 pointer-events-none">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <motion.div
                key={i}
                className="absolute w-px bg-gradient-to-b from-glow-cyan to-transparent"
                style={{ left: `${20 + i * 12}%`, height: '60%' }}
                animate={{ y: ['-30%', '130%'] }}
                transition={{
                  duration: 1.5 + i * 0.3,
                  repeat: Infinity,
                  ease: 'linear',
                  delay: i * 0.25,
                }}
              />
            ))}
          </div>
        )}

        {/* Labels */}
        <span
          className="relative z-10 font-bold tracking-[0.25em] uppercase"
          style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }}
        >
          OllaBridge
        </span>
        <span
          className="relative z-10 font-semibold mt-0.5"
          style={{
            fontSize: 14,
            color: isOnline ? '#00e5ff' : '#ef4444',
            textShadow: isOnline
              ? '0 0 10px rgba(0,229,255,0.6), 0 0 30px rgba(0,229,255,0.3)'
              : '0 0 8px rgba(239,68,68,0.4)',
          }}
        >
          {isOnline ? 'LLM CORE' : 'OFFLINE'}
        </span>

        {defaultModel && isOnline && (
          <motion.span
            className="relative z-10 mt-1 max-w-[110px] truncate"
            style={{ fontSize: 9, color: 'rgba(255,255,255,0.25)' }}
            animate={{ opacity: [0.3, 0.6, 0.3] }}
            transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
          >
            {defaultModel}
          </motion.span>
        )}

        {/* Bottom bloom inside core */}
        <div
          className="absolute bottom-0 left-1/2 -translate-x-1/2 w-full h-[30%] pointer-events-none"
          style={{
            background: isOnline
              ? 'radial-gradient(ellipse at 50% 100%, rgba(139,92,246,0.15), transparent)'
              : 'none',
          }}
        />
      </motion.div>

      {/* === Floating particles === */}
      {isOnline &&
        [0, 1, 2, 3, 4, 5].map((i) => (
          <motion.div
            key={`p-${i}`}
            className="absolute rounded-full pointer-events-none"
            style={{
              width: 4 + (i % 2) * 2,
              height: 4 + (i % 2) * 2,
              background: i % 2 === 0
                ? 'radial-gradient(circle, #00e5ff 20%, rgba(0,229,255,0.3) 50%, transparent 100%)'
                : 'radial-gradient(circle, #8b5cf6 20%, rgba(139,92,246,0.3) 50%, transparent 100%)',
              boxShadow: i % 2 === 0
                ? '0 0 4px rgba(0,229,255,0.6)'
                : '0 0 4px rgba(139,92,246,0.6)',
            }}
            animate={{
              x: [
                Math.cos((i * Math.PI) / 3) * 100,
                Math.cos((i * Math.PI) / 3 + 1) * 115,
                Math.cos((i * Math.PI) / 3) * 100,
              ],
              y: [
                Math.sin((i * Math.PI) / 3) * 100,
                Math.sin((i * Math.PI) / 3 + 1) * 115,
                Math.sin((i * Math.PI) / 3) * 100,
              ],
              opacity: [0.3, 0.8, 0.3],
            }}
            transition={{
              duration: 4 + i * 0.5,
              repeat: Infinity,
              ease: 'easeInOut',
              delay: i * 0.4,
            }}
          />
        ))}

      {/* === Status indicator dot === */}
      <div className="absolute bottom-3 right-6">
        <motion.div
          className="w-3.5 h-3.5 rounded-full"
          style={{
            background: isOnline
              ? 'radial-gradient(circle, #00e5ff 25%, rgba(0,229,255,0.4) 55%, transparent 100%)'
              : 'radial-gradient(circle, #ef4444 25%, rgba(239,68,68,0.4) 55%, transparent 100%)',
            boxShadow: isOnline
              ? '0 0 10px rgba(0,229,255,0.7), 0 0 25px rgba(0,229,255,0.3)'
              : '0 0 8px rgba(239,68,68,0.5)',
          }}
          animate={isOnline ? { scale: [1, 1.4, 1], opacity: [0.7, 1, 0.7] } : {}}
          transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
        />
      </div>
    </div>
  )
}
