import { HelpCircle } from 'lucide-react'
import { useHealth } from '../lib/hooks'
import type { Page } from '../App'

const PAGE_TITLES: Record<Page, string> = {
  dashboard: 'AI Distribution System',
  sources: 'Sources & Access',
  models: 'Model Inventory',
  runtimes: 'Local Runtimes',
  nodes: 'Node Fleet Manager',
  pairing: 'Device Pairing',
  cloud: 'Cloud Relay',
  settings: 'Settings',
}

export function TopHeader({ currentPage }: { currentPage: Page }) {
  const { data: health } = useHealth()
  const isOnline = health?.status === 'ok'

  return (
    <header className="h-16 flex items-center justify-between px-5 border-b border-white/5 bg-navy-900/70 backdrop-blur-sm z-10 shrink-0">
      {/* Brand block: logo + wordmark + page title */}
      <div className="flex items-center gap-4 min-w-0">
        <div className="flex items-center gap-3 shrink-0">
          <div
            className="w-10 h-10 rounded-2xl flex items-center justify-center"
            style={{
              background: 'linear-gradient(135deg, rgba(0,229,255,0.14), rgba(139,92,246,0.14))',
              border: '1px solid rgba(255,255,255,0.08)',
              boxShadow: '0 0 24px rgba(0,229,255,0.08)',
            }}
          >
            <div
              className="w-5 h-5 rounded-full"
              style={{
                border: '2.5px solid rgba(0,229,255,0.85)',
                boxShadow: '0 0 12px rgba(0,229,255,0.5), inset 0 0 8px rgba(0,229,255,0.25)',
              }}
            />
          </div>
          <span className="text-xl font-bold tracking-tight text-white">OllaBridge</span>
        </div>
        <div className="h-6 w-px bg-white/10 shrink-0" />
        <h1 className="text-base font-medium text-white/55 truncate">{PAGE_TITLES[currentPage]}</h1>
      </div>

      <div className="flex items-center gap-3">
        {health && (
          <div
            className="flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-medium"
            style={{
              background: isOnline ? 'rgba(20,184,166,0.08)' : 'rgba(236,72,153,0.08)',
              border: `1px solid ${isOnline ? 'rgba(20,184,166,0.25)' : 'rgba(236,72,153,0.25)'}`,
              color: isOnline ? '#2dd4bf' : '#f472b6',
            }}
          >
            <span
              className={`w-2 h-2 rounded-full ${isOnline ? 'bg-glow-teal animate-pulse' : 'bg-glow-pink'}`}
              style={{ boxShadow: isOnline ? '0 0 8px rgba(45,212,191,0.8)' : 'none' }}
            />
            {isOnline ? 'Online' : 'Offline'}
          </div>
        )}
        <button className="w-9 h-9 rounded-full flex items-center justify-center text-white/30 border border-white/8 hover:text-white/60 hover:bg-white/5 transition-colors">
          <HelpCircle size={16} />
        </button>
      </div>
    </header>
  )
}
