import { motion } from 'framer-motion'
import { LayoutDashboard, Database, Brain, Boxes, Link2, Cloud, Settings } from 'lucide-react'
import type { Page } from '../App'

const NAV_ITEMS: { id: Page; icon: typeof LayoutDashboard; label: string }[] = [
  { id: 'dashboard', icon: LayoutDashboard, label: 'Overview' },
  { id: 'sources', icon: Database, label: 'Sources' },
  { id: 'models', icon: Brain, label: 'Models' },
  { id: 'nodes', icon: Boxes, label: 'Nodes' },
  { id: 'pairing', icon: Link2, label: 'Pairing' },
  { id: 'cloud', icon: Cloud, label: 'Cloud' },
  { id: 'settings', icon: Settings, label: 'Settings' },
]

export function SidebarNav({ activePage, onNavigate }: { activePage: Page; onNavigate: (p: Page) => void }) {
  return (
    <aside className="w-[72px] h-full flex flex-col items-center py-4 gap-0.5 border-r border-white/5 bg-navy-900/80 backdrop-blur-sm z-20">
      <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-glow-cyan/30 to-glow-violet/30 border border-white/10 flex items-center justify-center mb-3">
        <div className="w-4 h-4 rounded-full bg-glow-cyan/60" />
      </div>
      <nav className="flex flex-col gap-0.5 flex-1">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          const active = activePage === item.id
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`relative w-14 rounded-xl flex flex-col items-center justify-center gap-0.5 py-2 transition-all duration-200 group ${active ? 'text-glow-cyan bg-glow-cyan/10' : 'text-white/30 hover:text-white/60 hover:bg-white/5'}`}
              title={item.label}
            >
              {active && (
                <motion.div
                  layoutId="sidebar-active"
                  className="absolute inset-0 rounded-xl bg-glow-cyan/10 border border-glow-cyan/20"
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
              <Icon size={17} className="relative z-10" />
              <span className="relative z-10 text-[9px] font-medium leading-none tracking-wide">
                {item.label}
              </span>
            </button>
          )
        })}
      </nav>
    </aside>
  )
}
