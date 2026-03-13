import { useState } from 'react'
import { SidebarNav } from './layouts/SidebarNav'
import { TopHeader } from './layouts/TopHeader'
import { DashboardPage } from './pages/dashboard/DashboardPage'
import { ModelsPage } from './pages/models/ModelsPage'
import { PairingPage } from './pages/pairing/PairingPage'
import { SettingsPage } from './pages/settings/SettingsPage'

export type Page = 'dashboard' | 'traffic' | 'models' | 'nodes' | 'pairing' | 'settings'

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')

  return (
    <div className="flex h-full w-full bg-navy-900">
      <SidebarNav activePage={page} onNavigate={setPage} />
      <div className="flex flex-col flex-1 min-w-0">
        <TopHeader currentPage={page} />
        <main className="flex-1 min-h-0 overflow-hidden relative">
          {page === 'dashboard' && <DashboardPage onNavigate={setPage} />}
          {page === 'models' && <ModelsPage onNavigate={setPage} />}
          {page === 'pairing' && <PairingPage />}
          {page === 'settings' && <SettingsPage />}
          {!['dashboard', 'models', 'pairing', 'settings'].includes(page) && (
            <div className="flex items-center justify-center h-full text-white/30 text-lg">
              {page.charAt(0).toUpperCase() + page.slice(1)} — coming soon
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
