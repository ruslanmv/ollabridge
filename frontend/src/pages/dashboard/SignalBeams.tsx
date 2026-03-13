interface SignalBeamsProps {
  isOnline: boolean
  isFlowing: boolean
  pulseCount?: number
}

export function SignalBeams({ isOnline, isFlowing, pulseCount = 0 }: SignalBeamsProps) {
  if (!isOnline) return null

  const beams: { id: string; d: string; color: string; delay: number }[] = [
    { id: 'beam-1', d: 'M 50,62 C 43,71 25,79 14,89', color: '#82f7ff', delay: 0 },
    { id: 'beam-2', d: 'M 50,62 C 47,71 37,79 30,89', color: '#b58cff', delay: 0.35 },
    { id: 'beam-4', d: 'M 50,62 C 53,71 63,79 70,89', color: '#b58cff', delay: 0.7 },
    { id: 'beam-5', d: 'M 50,62 C 57,71 75,79 86,89', color: '#82f7ff', delay: 1.05 },
  ]

  return (
    <g>
      <defs>
        <filter id="beam-glow-sm"><feGaussianBlur stdDeviation="1.2" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        <filter id="beam-glow-lg"><feGaussianBlur stdDeviation="3.2" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        <filter id="beam-bloom"><feGaussianBlur stdDeviation="7" /></filter>
      </defs>

      {beams.map((beam) => (
        <g key={beam.id}>
          <path d={beam.d} fill="none" stroke={beam.color} strokeWidth="4" strokeOpacity="0.045" filter="url(#beam-bloom)" vectorEffect="non-scaling-stroke" />
          <path d={beam.d} fill="none" stroke={beam.color} strokeWidth="1.6" strokeOpacity={isFlowing ? '0.2' : '0.1'} filter="url(#beam-glow-lg)" vectorEffect="non-scaling-stroke" />
          <path d={beam.d} fill="none" stroke={beam.color} strokeWidth="0.7" strokeOpacity={isFlowing ? '0.45' : '0.18'} filter="url(#beam-glow-sm)" vectorEffect="non-scaling-stroke" />
          {isFlowing && (
            <>
              <path d={beam.d} fill="none" stroke={beam.color} strokeWidth="1.5" strokeOpacity="0.95" strokeLinecap="round" filter="url(#beam-glow-sm)" vectorEffect="non-scaling-stroke" strokeDasharray="5 96">
                <animate attributeName="stroke-dashoffset" values="100;0" dur="2.4s" begin={`${beam.delay}s`} repeatCount="indefinite" />
              </path>
              {Array.from({ length: Math.max(1, Math.min(3, pulseCount)) }).map((_, i) => (
                <g key={`${beam.id}-particle-${i}`}>
                  <circle r="3.4" fill={beam.color} opacity="0.22" filter="url(#beam-bloom)">
                    <animateMotion dur="2.5s" repeatCount="indefinite" begin={`${beam.delay + i * 0.32}s`} path={beam.d.replace(/(\d+),(\d+)/g, '$1 $2')} />
                    <animate attributeName="opacity" values="0;0.2;0" dur="2.5s" begin={`${beam.delay + i * 0.32}s`} repeatCount="indefinite" />
                  </circle>
                  <circle r="1.2" fill={beam.color} filter="url(#beam-glow-sm)">
                    <animateMotion dur="2.5s" repeatCount="indefinite" begin={`${beam.delay + i * 0.32}s`} path={beam.d.replace(/(\d+),(\d+)/g, '$1 $2')} />
                    <animate attributeName="opacity" values="0;1;0" dur="2.5s" begin={`${beam.delay + i * 0.32}s`} repeatCount="indefinite" />
                  </circle>
                </g>
              ))}
            </>
          )}
        </g>
      ))}
    </g>
  )
}
