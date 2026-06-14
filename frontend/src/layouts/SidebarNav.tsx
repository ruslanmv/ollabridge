import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  Brain,
  Boxes,
  Link2,
  Cloud,
  Settings,
  PlugZap,
  Server,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react'
import type { Page } from '../App'

const NAV_ITEMS: { id: Page; icon: typeof LayoutDashboard; label: string }[] = [
  { id: 'dashboard', icon: LayoutDashboard, label: 'Overview' },
  { id: 'sources', icon: PlugZap, label: 'Sources' },
  { id: 'models', icon: Brain, label: 'Models' },
  { id: 'runtimes', icon: Server, label: 'Runtimes' },
  { id: 'nodes', icon: Boxes, label: 'Nodes' },
  { id: 'pairing', icon: Link2, label: 'Pairing' },
  { id: 'cloud', icon: Cloud, label: 'Cloud' },
  { id: 'settings', icon: Settings, label: 'Settings' },
]

const COLLAPSED_KEY = 'ollabridge_sidebar_collapsed'

export function SidebarNav({ activePage, onNavigate }: { activePage: Page; onNavigate: (p: Page) => void }) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === 'true')

  const toggle = () => {
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSED_KEY, String(!c))
      return !c
    })
  }

  return (
    <aside
      className={`${collapsed ? 'w-[72px]' : 'w-[200px]'} h-full flex flex-col py-4 px-3 border-r border-white/5 bg-navy-900/80 backdrop-blur-sm z-20 transition-[width] duration-200 shrink-0`}
    >
      <nav className="flex flex-col gap-1 flex-1">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          const active = activePage === item.id
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`relative rounded-xl flex items-center gap-3 px-3 py-2.5 transition-all duration-200 ${collapsed ? 'justify-center' : ''} ${active ? 'text-glow-cyan' : 'text-white/40 hover:text-white/70 hover:bg-white/5'}`}
              title={item.label}
            >
              {active && (
                <motion.div
                  layoutId="sidebar-active"
                  className="absolute inset-0 rounded-xl bg-glow-cyan/10 border border-glow-cyan/20"
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
              <Icon size={18} className="relative z-10 shrink-0" />
              {!collapsed && (
                <span className="relative z-10 text-sm font-medium leading-none">{item.label}</span>
              )}
            </button>
          )
        })}
      </nav>

      <button
        onClick={toggle}
        className="mt-2 w-10 h-10 rounded-xl flex items-center justify-center text-white/30 border border-white/8 hover:text-white/60 hover:bg-white/5 transition-colors self-start"
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
      </button>
    </aside>
  )
}
