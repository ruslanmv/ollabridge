import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { Activity, Globe, Mail, MonitorSmartphone, Plus, Search, Smartphone, Trash2, Watch } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useConsumerNodes, usePairedDevices } from '../../lib/hooks'
import { api, type ConsumerNode, type ConsumerNodeStatus } from '../../lib/api'

type Protocol = 'WebSocket' | 'SSE' | 'Webhook'

const HEARTBEAT_THRESHOLD_MS = 120_000 // 2 minutes

function iconFor(kind: string) {
  switch (kind) {
    case 'mobile': return Smartphone
    case 'watch': return Watch
    case 'web': return Globe
    case 'email': return Mail
    case 'avatar': return MonitorSmartphone
    default: return Activity
  }
}

function colorForStatus(status: ConsumerNodeStatus) {
  if (status === 'online') return '#14b8a6'
  if (status === 'waiting') return '#f59e0b'
  return '#ec4899'
}

function deriveStatus(node: ConsumerNode, pairedDeviceIds: Set<string>): ConsumerNodeStatus {
  if (!node.enabled) return 'offline'
  if (node.paired_device_id && pairedDeviceIds.has(node.paired_device_id)) return 'online'
  if (node.last_seen && Date.now() - node.last_seen * 1000 < HEARTBEAT_THRESHOLD_MS) return 'online'
  return 'waiting'
}

export function NodesPage() {
  const { data: nodesData } = useConsumerNodes()
  const { data: devicesData } = usePairedDevices()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [protocolFilter, setProtocolFilter] = useState<'all' | Protocol>('all')
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newKind, setNewKind] = useState('custom')
  const [newProtocol, setNewProtocol] = useState<Protocol>('WebSocket')

  const pairedDeviceIds = useMemo(() => {
    const ids = new Set<string>()
    for (const d of devicesData?.devices ?? []) ids.add(d.device_id)
    return ids
  }, [devicesData])

  const nodes = useMemo(() => {
    return (nodesData?.nodes ?? []).map((node) => ({
      ...node,
      status: deriveStatus(node, pairedDeviceIds),
    }))
  }, [nodesData, pairedDeviceIds])

  const filtered = nodes.filter(
    (n) =>
      (search ? n.name.toLowerCase().includes(search.toLowerCase()) : true) &&
      (protocolFilter === 'all' ? true : n.protocol === protocolFilter),
  )

  const activeConnections = nodes.filter((n) => n.status === 'online').length

  const handleToggle = async (node: ConsumerNode & { status: ConsumerNodeStatus }) => {
    await api.patchConsumerNode(node.id, { enabled: !node.enabled })
    queryClient.invalidateQueries({ queryKey: ['consumerNodes'] })
  }

  const handleDelete = async (id: string) => {
    await api.deleteConsumerNode(id)
    queryClient.invalidateQueries({ queryKey: ['consumerNodes'] })
  }

  const handleAdd = async () => {
    if (!newName.trim()) return
    await api.createConsumerNode({
      name: newName.trim(),
      kind: newKind,
      protocol: newProtocol,
    })
    setNewName('')
    setNewKind('custom')
    setNewProtocol('WebSocket')
    setAdding(false)
    queryClient.invalidateQueries({ queryKey: ['consumerNodes'] })
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-6">
      <div className="max-w-6xl mx-auto space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-4 items-stretch">
          <div className="glass-card p-5">
            <div className="text-white/40 text-xs uppercase tracking-[0.18em]">Active Connections</div>
            <div className="text-4xl font-semibold text-cyan-300 mt-2">
              {activeConnections} / {nodes.length} Active
            </div>
          </div>
          <div className="glass-card p-5">
            <div className="text-white/40 text-xs uppercase tracking-[0.18em]">Registered Nodes</div>
            <div className="text-4xl font-semibold text-cyan-300 mt-2">{nodes.length}</div>
          </div>
          <div className="flex flex-col gap-3">
            <button
              onClick={() => setAdding(!adding)}
              className="px-5 py-3 rounded-2xl text-sm font-semibold text-white bg-emerald-500/80 hover:bg-emerald-500 transition-colors inline-flex items-center justify-center gap-2"
            >
              <Plus size={16} /> Add Consumer Node
            </button>
          </div>
        </div>

        {adding && (
          <motion.div className="glass-card p-5 space-y-3" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
            <div className="text-white/70 text-sm font-semibold">New Consumer Node</div>
            <div className="flex flex-col md:flex-row gap-3">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Node name..."
                className="flex-1 rounded-xl px-3 py-2.5 text-sm text-white/85 bg-white/[0.04] border border-white/10 outline-none focus:border-cyan-400/50"
              />
              <select
                value={newKind}
                onChange={(e) => setNewKind(e.target.value)}
                className="rounded-xl px-3 py-2.5 text-sm text-white/85 bg-white/[0.04] border border-white/10 outline-none"
              >
                <option value="custom">Custom</option>
                <option value="mobile">Mobile</option>
                <option value="watch">Watch</option>
                <option value="web">Web</option>
                <option value="email">Email</option>
                <option value="avatar">Avatar</option>
              </select>
              <select
                value={newProtocol}
                onChange={(e) => setNewProtocol(e.target.value as Protocol)}
                className="rounded-xl px-3 py-2.5 text-sm text-white/85 bg-white/[0.04] border border-white/10 outline-none"
              >
                <option value="WebSocket">WebSocket</option>
                <option value="SSE">SSE</option>
                <option value="Webhook">Webhook</option>
              </select>
              <button onClick={handleAdd} className="px-5 py-2.5 rounded-xl text-sm font-semibold text-white bg-cyan-500/70 hover:bg-cyan-500 transition-colors">
                Create
              </button>
            </div>
          </motion.div>
        )}

        <div className="glass-card p-4 flex flex-col md:flex-row gap-3 md:items-center md:justify-between">
          <div className="flex flex-1 gap-3">
            <div className="flex-1 relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search nodes..."
                className="w-full rounded-xl pl-9 pr-3 py-2.5 text-sm text-white/85 bg-white/[0.04] border border-white/10 outline-none focus:border-cyan-400/50"
              />
            </div>
            <select
              value={protocolFilter}
              onChange={(e) => setProtocolFilter(e.target.value as 'all' | Protocol)}
              className="rounded-xl px-3 py-2.5 text-sm text-white/85 bg-white/[0.04] border border-white/10 outline-none"
            >
              <option value="all">All protocols</option>
              <option value="WebSocket">WebSocket</option>
              <option value="SSE">SSE</option>
              <option value="Webhook">Webhook</option>
            </select>
          </div>
          <div className="flex items-center gap-4 text-xs text-white/45">
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full" style={{ background: '#14b8a6' }} /> Online
            </span>
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full" style={{ background: '#f59e0b' }} /> Waiting
            </span>
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full" style={{ background: '#ec4899' }} /> Offline
            </span>
          </div>
        </div>

        {filtered.length === 0 && (
          <div className="glass-card p-8 text-center text-white/40 text-sm">
            {nodes.length === 0
              ? 'No consumer nodes registered. Pair a device or click "Add Consumer Node" to get started.'
              : 'No nodes match your search.'}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {filtered.map((node) => {
            const Icon = iconFor(node.kind)
            const statusColor = colorForStatus(node.status)
            return (
              <motion.div key={node.id} className="glass-card p-5" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex gap-3">
                    <div className="w-11 h-11 rounded-2xl flex items-center justify-center border border-white/10 bg-white/[0.03]">
                      <Icon size={20} className="text-cyan-300" />
                    </div>
                    <div>
                      <div className="text-white/90 font-semibold text-2xl leading-none mb-1">{node.name}</div>
                      <div className="text-xs text-white/45">
                        Protocol: <span className="text-cyan-300">[ {node.protocol} ]</span>
                        {node.paired_device_id && (
                          <span className="ml-2 text-white/30">paired</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-sm font-medium" style={{ color: statusColor }}>
                    <span
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ background: statusColor, boxShadow: `0 0 10px ${statusColor}` }}
                    />{' '}
                    {node.status.toUpperCase()}
                  </div>
                </div>
                <p className="text-white/70 text-sm mt-5 mb-5">{node.description || `${node.kind} consumer node`}</p>
                <div className="flex items-center justify-between">
                  <label className="inline-flex items-center gap-3 cursor-pointer">
                    <div
                      className={`w-11 h-6 rounded-full transition-colors ${node.enabled ? 'bg-emerald-400/60' : 'bg-white/10'}`}
                      onClick={() => handleToggle(node)}
                    >
                      <div className={`w-5 h-5 rounded-full bg-white mt-0.5 transition-all ${node.enabled ? 'ml-5' : 'ml-0.5'}`} />
                    </div>
                    <span className="text-xs text-white/45">{node.enabled ? 'Routing enabled' : 'Disabled'}</span>
                  </label>
                  <button
                    onClick={() => handleDelete(node.id)}
                    className="w-9 h-9 rounded-xl border border-white/10 bg-white/[0.03] flex items-center justify-center text-white/35 hover:text-red-300 hover:border-red-500/20"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </motion.div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
