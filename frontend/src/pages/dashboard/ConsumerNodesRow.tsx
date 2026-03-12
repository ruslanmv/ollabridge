import { motion } from 'framer-motion'
import { useHealth } from '../../lib/hooks'

type ConsumerNode = {
  id: string
  label: string
  icon: string
  status: 'online' | 'waiting' | 'offline' | 'error'
  title: string
  desc: string
  color: string
}

const CONSUMER_NODES: ConsumerNode[] = [
  {
    id: '3d-avatar',
    label: '3D Avatar',
    icon: 'avatar',
    status: 'waiting',
    title: '3D Avatar Chatbot',
    desc: 'Interactive 3D avatar with voice, pairing, and persona support.',
    color: '#8b5cf6',
  },
  {
    id: 'mobile',
    label: 'Mobile App',
    icon: 'phone',
    status: 'waiting',
    title: 'Tech Summary',
    desc: 'Real-time AI briefings delivered to your mobile device.',
    color: '#6366f1',
  },
  {
    id: 'watch',
    label: 'Smart Watch',
    icon: 'watch',
    status: 'waiting',
    title: 'Wrist Notifications',
    desc: 'Context-aware LLM summaries on your wrist.',
    color: '#ec4899',
  },
  {
    id: 'web',
    label: 'Web Portal',
    icon: 'globe',
    status: 'waiting',
    title: 'Interactive Dashboard',
    desc: 'Browser-based dashboard for interactive AI queries.',
    color: '#00e5ff',
  },
  {
    id: 'email',
    label: 'Email Feed',
    icon: 'mail',
    status: 'waiting',
    title: 'AI Digest',
    desc: 'Automated digest emails generated from live LLM output.',
    color: '#f59e0b',
  },
]

/** Bottom consumer node cards — output channels that receive from OllaBridge. */
export function ConsumerNodesRow() {
  const { data: health } = useHealth()
  const isOnline = health?.status === 'ok'

  const nodes = CONSUMER_NODES.map((node) => {
    // 3D Avatar and Web Portal become online when system is live
    if (isOnline && (node.id === 'web' || node.id === '3d-avatar')) {
      return { ...node, status: 'online' as const }
    }
    return node
  })

  return (
    <div className="relative flex flex-col items-center">
      {/* Section label */}
      <div className="mb-3 inline-flex items-center gap-2 px-3 py-1 rounded-md bg-white/[0.04] border border-white/[0.06]">
        <span className="text-[11px] font-semibold text-white/40 uppercase tracking-wider">
          Consumer Nodes
        </span>
        <span className="text-[10px] text-white/25">
          {nodes.filter((n) => n.status === 'online').length}/{nodes.length} active
        </span>
      </div>

      {/* Cards row */}
      <div className="flex gap-3 justify-center flex-wrap">
        {nodes.map((node, i) => (
          <motion.div
            key={node.id}
            className="flex-1 min-w-[150px] max-w-[200px] cursor-pointer transition-all"
            style={{
              background: 'linear-gradient(145deg, rgba(12,18,50,0.7), rgba(8,12,35,0.55))',
              backdropFilter: 'blur(16px)',
              border: `1px solid ${node.status === 'online' ? node.color + '25' : 'rgba(255,255,255,0.06)'}`,
              borderRadius: 16,
              boxShadow:
                node.status === 'online'
                  ? `inset 0 1px 0 rgba(255,255,255,0.03), 0 0 20px ${node.color}10, 0 4px 24px rgba(0,0,0,0.3)`
                  : 'inset 0 1px 0 rgba(255,255,255,0.03), 0 4px 24px rgba(0,0,0,0.3)',
              overflow: 'hidden',
            }}
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.06 * i, duration: 0.5, ease: 'easeOut' }}
            whileHover={{
              y: -3,
              scale: 1.02,
              borderColor: node.color + '40',
              boxShadow: `inset 0 1px 0 rgba(255,255,255,0.05), 0 0 25px ${node.color}15, 0 8px 30px rgba(0,0,0,0.35)`,
            }}
          >
            {/* Header */}
            <div className="flex items-center gap-2.5 px-3.5 pt-3 pb-1.5">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                style={{
                  background: `${node.color}15`,
                  border: `1px solid ${node.color}30`,
                }}
              >
                <NodeIcon type={node.icon} color={node.color} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[12px] font-semibold text-white/85 truncate">{node.label}</div>
              </div>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-white/15 shrink-0">
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </div>

            {/* Content */}
            <div className="px-3.5 pb-2.5">
              <div className="text-[10px] font-semibold text-white/50 mb-0.5">{node.title}</div>
              <div className="text-[9px] text-white/25 leading-relaxed line-clamp-2">{node.desc}</div>
            </div>

            {/* Status */}
            <div
              className="flex items-center gap-2 px-3.5 py-1.5"
              style={{
                borderTop: '1px solid rgba(255,255,255,0.04)',
                background: 'rgba(0,0,0,0.15)',
              }}
            >
              <motion.div
                className="w-2 h-2 rounded-full"
                style={{
                  backgroundColor:
                    node.status === 'online'
                      ? node.color
                      : node.status === 'error'
                        ? '#ec4899'
                        : 'rgba(255,255,255,0.15)',
                  boxShadow:
                    node.status === 'online' ? `0 0 6px ${node.color}80` : 'none',
                }}
                animate={
                  node.status === 'online' ? { opacity: [0.6, 1, 0.6] } : {}
                }
                transition={{ duration: 2, repeat: Infinity }}
              />
              <span className="text-[9px] text-white/30 uppercase tracking-wider font-medium">
                {node.status}
              </span>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}

function NodeIcon({ type, color }: { type: string; color: string }) {
  const style = { color }

  switch (type) {
    case 'avatar':
      return (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={style}>
          <circle cx="12" cy="8" r="5" />
          <path d="M20 21a8 8 0 0 0-16 0" />
        </svg>
      )
    case 'phone':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={style}>
          <rect x="5" y="2" width="14" height="20" rx="2" ry="2" />
          <line x1="12" y1="18" x2="12.01" y2="18" />
        </svg>
      )
    case 'watch':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={style}>
          <circle cx="12" cy="12" r="7" />
          <polyline points="12 9 12 12 13.5 13.5" />
          <path d="M16.51 17.35l-.35 3.83a2 2 0 0 1-2 1.82H9.83a2 2 0 0 1-2-1.82l-.35-3.83m.01-10.7.35-3.83A2 2 0 0 1 9.83 1h4.35a2 2 0 0 1 2 1.82l.35 3.83" />
        </svg>
      )
    case 'mail':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={style}>
          <rect x="2" y="4" width="20" height="16" rx="2" />
          <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
        </svg>
      )
    case 'globe':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={style}>
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
      )
    default:
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={style}>
          <rect x="2" y="2" width="20" height="8" rx="2" />
          <rect x="2" y="14" width="20" height="8" rx="2" />
        </svg>
      )
  }
}
