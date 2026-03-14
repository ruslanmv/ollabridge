import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { useConsumerNodes, usePairedDevices } from '../../lib/hooks'
import type { ConsumerNode, ConsumerNodeStatus } from '../../lib/api'

const HEARTBEAT_THRESHOLD_MS = 120_000

function deriveStatus(node: ConsumerNode, pairedDeviceIds: Set<string>): ConsumerNodeStatus {
  if (!node.enabled) return 'offline'
  if (node.paired_device_id && pairedDeviceIds.has(node.paired_device_id)) return 'online'
  if (node.last_seen && Date.now() - node.last_seen * 1000 < HEARTBEAT_THRESHOLD_MS) return 'online'
  return 'waiting'
}

function colorForKind(kind: string): string {
  switch (kind) {
    case 'avatar': return '#8b5cf6'
    case 'mobile': return '#68f4ff'
    case 'watch': return '#68f4ff'
    case 'web': return '#68f4ff'
    case 'email': return '#f7b733'
    default: return '#68f4ff'
  }
}

export function ConsumerNodesRow() {
  const { data: nodesData } = useConsumerNodes()
  const { data: devicesData } = usePairedDevices()

  const pairedDeviceIds = useMemo(() => {
    const ids = new Set<string>()
    for (const d of devicesData?.devices ?? []) ids.add(d.device_id)
    return ids
  }, [devicesData])

  const nodes = useMemo(() => {
    return (nodesData?.nodes ?? []).map((node) => ({
      ...node,
      status: deriveStatus(node, pairedDeviceIds),
      color: colorForKind(node.kind),
    }))
  }, [nodesData, pairedDeviceIds])

  if (nodes.length === 0) {
    return (
      <div className="max-w-[1440px] mx-auto">
        <div className="flex items-center justify-center mb-3">
          <div className="px-4 py-1.5 rounded-full text-[10px] uppercase tracking-[0.24em] text-white/35 border border-white/8 bg-white/[0.03]">
            Consumer Nodes
          </div>
        </div>
        <div className="text-center text-white/25 text-xs py-4">
          No consumer nodes registered. Pair a device to get started.
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-[1440px] mx-auto">
      <div className="flex items-center justify-center mb-3">
        <div className="px-4 py-1.5 rounded-full text-[10px] uppercase tracking-[0.24em] text-white/35 border border-white/8 bg-white/[0.03]">
          Consumer Nodes
        </div>
      </div>

      <div className={`grid gap-3`} style={{ gridTemplateColumns: `repeat(${Math.min(nodes.length, 5)}, 1fr)` }}>
        {nodes.slice(0, 5).map((node, i) => (
          <motion.div
            key={node.id}
            className="rounded-3xl overflow-hidden"
            style={{
              background: 'linear-gradient(180deg, rgba(9,12,34,0.78), rgba(7,10,28,0.64))',
              border: `1px solid ${node.status === 'online' ? node.color + '33' : 'rgba(255,255,255,0.07)'}`,
              boxShadow: node.status === 'online' ? `0 0 28px ${node.color}10` : 'none',
              backdropFilter: 'blur(14px)',
            }}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.06 * i, duration: 0.35 }}
            whileHover={{ y: -4, scale: 1.01 }}
          >
            <div className="p-4 pb-3">
              <div className="flex items-start gap-3 mb-3">
                <div
                  className="w-9 h-9 rounded-2xl flex items-center justify-center shrink-0"
                  style={{ background: `${node.color}14`, border: `1px solid ${node.color}30` }}
                >
                  <NodeIcon type={node.kind} color={node.color} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-semibold text-white/88 truncate">{node.name}</div>
                  <div className="text-[11px] text-white/38 mt-0.5">{node.kind}</div>
                </div>
                <motion.div
                  className="w-2 h-2 rounded-full mt-1 shrink-0"
                  style={{
                    backgroundColor:
                      node.status === 'online' ? node.color : node.status === 'waiting' ? '#f59e0b' : 'rgba(255,255,255,0.16)',
                    boxShadow: node.status === 'online' ? `0 0 8px ${node.color}` : 'none',
                  }}
                  animate={node.status === 'online' ? { opacity: [0.55, 1, 0.55] } : { opacity: 0.8 }}
                  transition={{ duration: 1.8, repeat: Infinity }}
                />
              </div>

              <div className="text-[11px] text-white/28 leading-relaxed min-h-[52px]">
                {node.description || `${node.kind} consumer node`}
              </div>
            </div>

            <div className="px-4 py-2 border-t border-white/[0.05] bg-black/10 flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-[0.22em] text-white/30">{node.status}</span>
              <span className="text-[10px] text-white/20">{node.status === 'online' ? 'routing' : 'idle'}</span>
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
    case 'mobile':
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
    case 'email':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={style}>
          <rect x="2" y="4" width="20" height="16" rx="2" />
          <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
        </svg>
      )
    default:
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={style}>
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
      )
  }
}
