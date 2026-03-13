import { motion } from 'framer-motion'

/**
 * Cinematic layered background — 5 stacked layers:
 * 1. Deep navy base gradient
 * 2. Central blue spotlight
 * 3. Purple halo behind orb
 * 4. Edge vignette
 * 5. Atmospheric animated haze blobs
 */
export function BroadcastBackground() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {/* Layer 1: base gradient */}
      <div
        className="absolute inset-0"
        style={{
          background: 'linear-gradient(180deg, #060b1d 0%, #050914 40%, #070c1e 100%)',
        }}
      />

      {/* Layer 2: central blue spotlight */}
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse 60% 50% at 50% 36%, rgba(0,140,255,0.14), transparent)',
        }}
      />

      {/* Layer 3: purple halo behind orb area */}
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse 40% 35% at 50% 30%, rgba(140,60,255,0.1), transparent)',
        }}
      />

      {/* Layer 4: top warm accent */}
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse 50% 25% at 50% 5%, rgba(100,80,255,0.06), transparent)',
        }}
      />

      {/* Layer 5: edge vignette */}
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse 80% 80% at 50% 50%, transparent 50%, rgba(0,0,0,0.5) 100%)',
        }}
      />

      {/* Subtle grid lines */}
      <svg className="absolute inset-0 w-full h-full opacity-[0.025]">
        <defs>
          <pattern id="grid" width="60" height="60" patternUnits="userSpaceOnUse">
            <path d="M 60 0 L 0 0 0 60" fill="none" stroke="white" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
      </svg>

      {/* Animated atmospheric haze blobs */}
      <motion.div
        className="absolute w-[500px] h-[500px] rounded-full"
        style={{
          left: '30%',
          top: '15%',
          background: 'radial-gradient(circle, rgba(0,180,255,0.06), transparent 70%)',
          filter: 'blur(60px)',
        }}
        animate={{ x: [0, 30, 0], y: [0, -20, 0], scale: [1, 1.1, 1] }}
        transition={{ duration: 12, repeat: Infinity, ease: 'easeInOut' }}
      />

      <motion.div
        className="absolute w-[400px] h-[400px] rounded-full"
        style={{
          right: '20%',
          top: '25%',
          background: 'radial-gradient(circle, rgba(139,92,246,0.05), transparent 70%)',
          filter: 'blur(50px)',
        }}
        animate={{ x: [0, -20, 0], y: [0, 15, 0], scale: [1, 1.08, 1] }}
        transition={{ duration: 15, repeat: Infinity, ease: 'easeInOut' }}
      />

      <motion.div
        className="absolute w-[300px] h-[300px] rounded-full"
        style={{
          left: '50%',
          top: '60%',
          transform: 'translateX(-50%)',
          background: 'radial-gradient(circle, rgba(0,229,255,0.04), transparent 70%)',
          filter: 'blur(40px)',
        }}
        animate={{ scale: [1, 1.15, 1], opacity: [0.5, 0.8, 0.5] }}
        transition={{ duration: 10, repeat: Infinity, ease: 'easeInOut' }}
      />
    </div>
  )
}
