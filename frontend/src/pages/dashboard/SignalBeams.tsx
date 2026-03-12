import { motion } from 'framer-motion'

interface SignalBeamsProps {
  isOnline: boolean
}

/**
 * SVG bezier beam paths radiating from tower base to consumer node positions.
 * Each beam: base path + glow duplicate + animated bright stroke traveling along path.
 */
export function SignalBeams({ isOnline }: SignalBeamsProps) {
  if (!isOnline) return null

  // Beams fan from center-bottom (50%, ~68%) to consumer card positions
  const beams: { id: string; d: string; color: string; delay: number }[] = [
    {
      id: 'beam-1',
      d: 'M 50,68 C 42,76 22,82 10,92',
      color: '#00e5ff',
      delay: 0,
    },
    {
      id: 'beam-2',
      d: 'M 50,68 C 46,76 35,83 30,92',
      color: '#8b5cf6',
      delay: 0.4,
    },
    {
      id: 'beam-3',
      d: 'M 50,68 C 50,76 50,83 50,92',
      color: '#00e5ff',
      delay: 0.8,
    },
    {
      id: 'beam-4',
      d: 'M 50,68 C 54,76 65,83 70,92',
      color: '#8b5cf6',
      delay: 1.2,
    },
    {
      id: 'beam-5',
      d: 'M 50,68 C 58,76 78,82 90,92',
      color: '#00e5ff',
      delay: 1.6,
    },
  ]

  return (
    <g>
      {/* SVG defs for glow filters */}
      <defs>
        <filter id="beam-glow-sm">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id="beam-glow-lg">
          <feGaussianBlur stdDeviation="5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id="beam-bloom">
          <feGaussianBlur stdDeviation="8" />
        </filter>
      </defs>

      {beams.map((beam) => (
        <g key={beam.id}>
          {/* Layer 1: wide soft bloom */}
          <path
            d={beam.d}
            fill="none"
            stroke={beam.color}
            strokeWidth="4"
            strokeOpacity="0.06"
            filter="url(#beam-bloom)"
            vectorEffect="non-scaling-stroke"
          />

          {/* Layer 2: medium glow */}
          <path
            d={beam.d}
            fill="none"
            stroke={beam.color}
            strokeWidth="2"
            strokeOpacity="0.15"
            filter="url(#beam-glow-lg)"
            vectorEffect="non-scaling-stroke"
          />

          {/* Layer 3: core line */}
          <path
            d={beam.d}
            fill="none"
            stroke={beam.color}
            strokeWidth="1"
            strokeOpacity="0.35"
            filter="url(#beam-glow-sm)"
            vectorEffect="non-scaling-stroke"
          />

          {/* Layer 4: animated bright stroke traveling along path */}
          <motion.path
            d={beam.d}
            fill="none"
            stroke={beam.color}
            strokeWidth="2"
            strokeOpacity="0.9"
            strokeLinecap="round"
            filter="url(#beam-glow-sm)"
            vectorEffect="non-scaling-stroke"
            strokeDasharray="4 96"
            initial={{ strokeDashoffset: 100 }}
            animate={{ strokeDashoffset: [100, 0] }}
            transition={{
              duration: 2.2,
              repeat: Infinity,
              ease: 'linear',
              delay: beam.delay,
            }}
          />

          {/* Particle dot traveling along the path */}
          <BeamParticle d={beam.d} color={beam.color} delay={beam.delay} />
        </g>
      ))}
    </g>
  )
}

/** Animated dot that travels along a bezier path. */
function BeamParticle({ d, color, delay }: { d: string; color: string; delay: number }) {
  return (
    <>
      {/* Bloom behind particle */}
      <motion.circle
        r="4"
        fill={color}
        opacity="0.3"
        filter="url(#beam-bloom)"
      >
        <animateMotion
          dur="2.5s"
          repeatCount="indefinite"
          begin={`${delay}s`}
          path={d.replace(/(\d+),(\d+)/g, '$1 $2')}
        />
      </motion.circle>
      {/* Core particle */}
      <circle r="2" fill={color} filter="url(#beam-glow-sm)">
        <animateMotion
          dur="2.5s"
          repeatCount="indefinite"
          begin={`${delay}s`}
          path={d.replace(/(\d+),(\d+)/g, '$1 $2')}
        />
      </circle>
    </>
  )
}
