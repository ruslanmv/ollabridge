import { HelpCircle } from 'lucide-react'
import { useHealth } from '../lib/hooks'
import type { Page } from '../App'

const PAGE_TITLES: Record<Page, string> = {
  dashboard: 'AI Distribution System',
  sources: 'Sources',
  models: 'Model Inventory',
  nodes: 'Node Fleet Manager',
  pairing: 'Device Pairing',
  settings: 'Settings',
}

export function TopHeader({ currentPage }: { currentPage: Page }) {
  const { data: health } = useHealth()

  return (
    <header className="h-14 flex items-center justify-between px-6 border-b border-white/5 bg-navy-900/60 backdrop-blur-sm z-10 shrink-0">
      <h1 className="text-lg font-bold tracking-tight text-white/90">{PAGE_TITLES[currentPage]}</h1>
      <div className="flex items-center gap-3">
        {health && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 border border-white/5 text-xs">
            <span className={`w-2 h-2 rounded-full ${health.status === 'ok' ? 'bg-glow-teal animate-pulse' : 'bg-glow-pink'}`} />
            <span className="text-white/60">{health.status === 'ok' ? 'Online' : 'Offline'}</span>
          </div>
        )}
        <button className="w-8 h-8 rounded-lg flex items-center justify-center text-white/30 hover:text-white/60 hover:bg-white/5 transition-colors">
          <HelpCircle size={16} />
        </button>
      </div>
    </header>
  )
}
