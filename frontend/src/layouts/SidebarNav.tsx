import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  Activity,
  Brain,
  Server,
  Link2,
  Settings,
} from 'lucide-react'
import type { Page } from '../App'

const NAV_ITEMS: { id: Page; icon: typeof LayoutDashboard; label: string }[] = [
  { id: 'dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { id: 'traffic', icon: Activity, label: 'Traffic' },
  { id: 'models', icon: Brain, label: 'Models' },
  { id: 'nodes', icon: Server, label: 'Nodes' },
  { id: 'pairing', icon: Link2, label: 'Pairing' },
  { id: 'settings', icon: Settings, label: 'Settings' },
]

type Props = { activePage: Page; onNavigate: (p: Page) => void }

export function SidebarNav({ activePage, onNavigate }: Props) {
  return (
    <aside className="w-16 h-full flex flex-col items-center py-5 gap-2 border-r border-white/5 bg-navy-900/80 backdrop-blur-sm z-20">
      {/* Logo orb */}
      <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-glow-cyan/30 to-glow-violet/30 border border-white/10 flex items-center justify-center mb-4">
        <div className="w-4 h-4 rounded-full bg-glow-cyan/60" />
      </div>

      {/* Nav items */}
      <nav className="flex flex-col gap-1 flex-1">
        {NAV_ITEMS.map((item) => {
          const active = activePage === item.id
          const Icon = item.icon
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`relative w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200 group ${
                active
                  ? 'text-glow-cyan bg-glow-cyan/10'
                  : 'text-white/30 hover:text-white/60 hover:bg-white/5'
              }`}
              title={item.label}
            >
              {active && (
                <motion.div
                  layoutId="sidebar-active"
                  className="absolute inset-0 rounded-xl bg-glow-cyan/10 border border-glow-cyan/20"
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
              <Icon size={18} className="relative z-10" />
              {/* Tooltip */}
              <span className="absolute left-14 px-2 py-1 rounded-md bg-navy-700 text-xs text-white/80 whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-30 border border-white/10">
                {item.label}
              </span>
            </button>
          )
        })}
      </nav>
    </aside>
  )
}
