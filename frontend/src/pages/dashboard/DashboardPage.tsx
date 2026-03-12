import { useState, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { BroadcastBackground } from './BroadcastBackground'
import { TowerCanvas } from './TowerCanvas'
import { ConsumerNodesRow } from './ConsumerNodesRow'
import { StatusHud } from './StatusHud'
import { SetupWizard } from './SetupWizard'
import { useHealth } from '../../lib/hooks'
import type { Page } from '../../App'

const WIZARD_DISMISSED_KEY = 'ollabridge_wizard_dismissed'

export function DashboardPage({ onNavigate }: { onNavigate: (page: Page) => void }) {
  const { data: health, isLoading } = useHealth()
  const isOnline = health?.status === 'ok'

  // Show wizard for first-time / offline users
  const [wizardDismissed, setWizardDismissed] = useState(() => {
    return localStorage.getItem(WIZARD_DISMISSED_KEY) === 'true'
  })

  const showWizard = !isLoading && !isOnline && !wizardDismissed

  const handleDismissWizard = () => {
    setWizardDismissed(true)
    localStorage.setItem(WIZARD_DISMISSED_KEY, 'true')
  }

  // Auto-dismiss wizard once system comes online
  useEffect(() => {
    if (isOnline) {
      localStorage.setItem(WIZARD_DISMISSED_KEY, 'true')
    }
  }, [isOnline])

  return (
    <div className="relative w-full h-full overflow-hidden">
      {/* Background effects layer */}
      <BroadcastBackground />

      {/* Status HUD overlay */}
      <StatusHud />

      {/* Center tower visualization */}
      <div className="absolute inset-0 flex flex-col">
        <div className="flex-1 min-h-0 relative">
          <TowerCanvas onNavigate={onNavigate} />

          {/* Activation CTA overlay when offline but wizard dismissed */}
          <AnimatePresence>
            {!isOnline && wizardDismissed && !isLoading && (
              <motion.div
                className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <motion.button
                  className="pointer-events-auto px-6 py-3 rounded-2xl text-sm font-semibold"
                  style={{
                    background: 'linear-gradient(135deg, rgba(0,229,255,0.15), rgba(139,92,246,0.15))',
                    border: '1px solid rgba(0,229,255,0.25)',
                    color: '#00e5ff',
                    boxShadow: '0 0 30px rgba(0,229,255,0.08), 0 8px 32px rgba(0,0,0,0.3)',
                    backdropFilter: 'blur(12px)',
                  }}
                  animate={{
                    boxShadow: [
                      '0 0 30px rgba(0,229,255,0.08), 0 8px 32px rgba(0,0,0,0.3)',
                      '0 0 50px rgba(0,229,255,0.15), 0 8px 32px rgba(0,0,0,0.3)',
                      '0 0 30px rgba(0,229,255,0.08), 0 8px 32px rgba(0,0,0,0.3)',
                    ],
                  }}
                  transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setWizardDismissed(false)}
                >
                  Configure System
                </motion.button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Consumer nodes strip at bottom */}
        <div className="shrink-0 px-6 pb-5">
          <ConsumerNodesRow />
        </div>
      </div>

      {/* Setup Wizard overlay */}
      <AnimatePresence>
        {showWizard && <SetupWizard onDismiss={handleDismissWizard} />}
      </AnimatePresence>
    </div>
  )
}
