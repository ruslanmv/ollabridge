import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { Activity, Globe, Mail, MonitorSmartphone, Plus, Search, Smartphone, Trash2, Watch } from 'lucide-react'
import { usePairedDevices } from '../../lib/hooks'

type NodeStatus = 'online' | 'waiting' | 'offline'
type Protocol = 'WebSocket' | 'SSE' | 'Webhook'

type ConsumerNode = {
  id: string
  name: string
  kind: 'mobile' | 'watch' | 'web' | 'email' | 'avatar' | 'custom'
  protocol: Protocol
  description: string
  status: NodeStatus
  enabled: boolean
  pairedDeviceId?: string
  tps: number
}

const TEMPLATES: ConsumerNode[] = [
  { id: 'mobile-app', name: 'Mobile App', kind: 'mobile', protocol: 'WebSocket', description: 'Delivers real-time AI summaries and interactions.', status: 'waiting', enabled: true, tps: 80 },
  { id: 'smart-watch', name: 'Smart Watch', kind: 'watch', protocol: 'SSE', description: 'Provides context-aware notifications and commands.', status: 'waiting', enabled: true, tps: 45 },
  { id: 'web-portal', name: 'Web Portal', kind: 'web', protocol: 'WebSocket', description: 'Browser-based interface for complex interactions and settings.', status: 'waiting', enabled: true, tps: 120 },
  { id: 'email-feed', name: 'Email Feed', kind: 'email', protocol: 'Webhook', description: 'Automated digest emails generated from live LLM output.', status: 'offline', enabled: false, tps: 10 },
  { id: '3d-avatar', name: '3D Avatar', kind: 'avatar', protocol: 'WebSocket', description: 'Interactive avatar endpoint with voice and persona support.', status: 'offline', enabled: false, tps: 60 },
]

function iconFor(kind: ConsumerNode['kind']) {
  switch (kind) {
    case 'mobile': return Smartphone
    case 'watch': return Watch
    case 'web': return Globe
    case 'email': return Mail
    case 'avatar': return MonitorSmartphone
    default: return Activity
  }
}

function colorForStatus(status: NodeStatus) {
  if (status === 'online') return '#14b8a6'
  if (status === 'waiting') return '#f59e0b'
  return '#ec4899'
}

export function NodesPage() {
  const { data: devicesData } = usePairedDevices()
  const [search, setSearch] = useState('')
  const [protocolFilter, setProtocolFilter] = useState<'all' | Protocol>('all')
  const [enabledMap, setEnabledMap] = useState<Record<string, boolean>>({})

  const nodes = useMemo(() => {
    const devices: Array<{ device_id: string; label: string }> = devicesData?.devices ?? []
    return TEMPLATES.map((template) => {
      const matched = devices.find((d: { device_id: string; label: string }) => d.label.toLowerCase().includes(template.name.toLowerCase()) || template.name.toLowerCase().includes(d.label.toLowerCase()))
      const enabled = enabledMap[template.id] ?? template.enabled
      let status: NodeStatus = enabled ? 'waiting' : 'offline'
      if (matched && enabled) status = 'online'
      return { ...template, enabled, status, pairedDeviceId: matched?.device_id }
    })
  }, [devicesData, enabledMap])

  const filtered = nodes.filter((n) => (search ? n.name.toLowerCase().includes(search.toLowerCase()) : true) && (protocolFilter === 'all' ? true : n.protocol === protocolFilter))
  const activeConnections = nodes.filter((n) => n.status === 'online').length
  const totalTps = nodes.filter((n) => n.enabled).reduce((sum, n) => sum + n.tps, 0)

  return (
    <div className="h-full overflow-y-auto px-6 py-6">
      <div className="max-w-6xl mx-auto space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-4 items-stretch">
          <div className="glass-card p-5">
            <div className="text-white/40 text-xs uppercase tracking-[0.18em]">Active Connections</div>
            <div className="text-4xl font-semibold text-cyan-300 mt-2">{activeConnections} / {nodes.length} Active</div>
          </div>
          <div className="glass-card p-5">
            <div className="text-white/40 text-xs uppercase tracking-[0.18em]">Total Throughput (TPS)</div>
            <div className="text-4xl font-semibold text-cyan-300 mt-2">{totalTps} TPS</div>
          </div>
          <div className="flex flex-col gap-3">
            <button className="px-5 py-3 rounded-2xl text-sm font-semibold text-white bg-emerald-500/80 hover:bg-emerald-500 transition-colors inline-flex items-center justify-center gap-2"><Plus size={16} /> Add Consumer Node</button>
            <button className="px-5 py-3 rounded-2xl text-sm font-semibold text-red-300 bg-red-500/10 border border-red-500/20 hover:bg-red-500/15 transition-colors">Global Kill Switch</button>
          </div>
        </div>

        <div className="glass-card p-4 flex flex-col md:flex-row gap-3 md:items-center md:justify-between">
          <div className="flex flex-1 gap-3">
            <div className="flex-1 relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search nodes..." className="w-full rounded-xl pl-9 pr-3 py-2.5 text-sm text-white/85 bg-white/[0.04] border border-white/10 outline-none focus:border-cyan-400/50" />
            </div>
            <select value={protocolFilter} onChange={(e) => setProtocolFilter(e.target.value as 'all' | Protocol)} className="rounded-xl px-3 py-2.5 text-sm text-white/85 bg-white/[0.04] border border-white/10 outline-none">
              <option value="all">All protocols</option>
              <option value="WebSocket">WebSocket</option>
              <option value="SSE">SSE</option>
              <option value="Webhook">Webhook</option>
            </select>
          </div>
          <div className="flex items-center gap-4 text-xs text-white/45">
            <span className="flex items-center gap-2"><span className="w-2 h-2 rounded-full" style={{ background: '#14b8a6' }} /> Online</span>
            <span className="flex items-center gap-2"><span className="w-2 h-2 rounded-full" style={{ background: '#f59e0b' }} /> Waiting</span>
            <span className="flex items-center gap-2"><span className="w-2 h-2 rounded-full" style={{ background: '#ec4899' }} /> Offline</span>
          </div>
        </div>

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
                      <div className="text-xs text-white/45">Protocol Tag: <span className="text-cyan-300">[ {node.protocol} ]</span></div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-sm font-medium" style={{ color: statusColor }}>
                    <span className="w-2.5 h-2.5 rounded-full" style={{ background: statusColor, boxShadow: `0 0 10px ${statusColor}` }} /> {node.status.toUpperCase()}
                  </div>
                </div>
                <p className="text-white/70 text-sm mt-5 mb-5">{node.description}</p>
                <div className="flex items-center justify-between">
                  <label className="inline-flex items-center gap-3 cursor-pointer">
                    <div className={`w-11 h-6 rounded-full transition-colors ${node.enabled ? 'bg-emerald-400/60' : 'bg-white/10'}`} onClick={() => setEnabledMap((m) => ({ ...m, [node.id]: !node.enabled }))}>
                      <div className={`w-5 h-5 rounded-full bg-white mt-0.5 transition-all ${node.enabled ? 'ml-5' : 'ml-0.5'}`} />
                    </div>
                    <span className="text-xs text-white/45">{node.enabled ? 'Routing enabled' : 'Disabled'}</span>
                  </label>
                  <button className="w-9 h-9 rounded-xl border border-white/10 bg-white/[0.03] flex items-center justify-center text-white/35 hover:text-red-300 hover:border-red-500/20"><Trash2 size={16} /></button>
                </div>
              </motion.div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
