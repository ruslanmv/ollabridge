import { useState } from 'react'
import { SidebarNav } from './layouts/SidebarNav'
import { TopHeader } from './layouts/TopHeader'
import { DashboardPage } from './pages/dashboard/DashboardPage'
import { ModelsPage } from './pages/models/ModelsPage'
import { PairingPage } from './pages/pairing/PairingPage'
import { SettingsPage } from './pages/settings/SettingsPage'
import { SourcesPage } from './pages/sources/SourcesPage'
import { NodesPage } from './pages/nodes/NodesPage'

export type Page = 'dashboard' | 'sources' | 'models' | 'nodes' | 'pairing' | 'settings'

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')

  return (
    <div className="flex h-full w-full bg-navy-900">
      <SidebarNav activePage={page} onNavigate={setPage} />
      <div className="flex flex-col flex-1 min-w-0">
        <TopHeader currentPage={page} />
        <main className="flex-1 min-h-0 overflow-hidden relative">
          {page === 'dashboard' && <DashboardPage onNavigate={setPage} />}
          {page === 'sources' && <SourcesPage onNavigate={setPage} />}
          {page === 'models' && <ModelsPage onNavigate={setPage} />}
          {page === 'nodes' && <NodesPage />}
          {page === 'pairing' && <PairingPage />}
          {page === 'settings' && <SettingsPage />}
        </main>
      </div>
    </div>
  )
}