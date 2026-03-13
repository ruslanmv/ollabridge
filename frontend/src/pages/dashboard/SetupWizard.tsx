import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

type WizardStep = 'welcome' | 'template' | 'configure' | 'activate'

type Template = {
  id: string
  icon: string
  label: string
  desc: string
  color: string
  tags: string[]
}

const TEMPLATES: Template[] = [
  {
    id: 'smart-home',
    icon: '🏠',
    label: 'Smart Home Assistant',
    desc: 'HomePilot personas + 3D Avatar with voice control',
    color: '#14b8a6',
    tags: ['HomePilot', '3D Avatar', 'Voice'],
  },
  {
    id: 'news-dist',
    icon: '📰',
    label: 'AI News Distribution',
    desc: 'RSS input → Summarization → Email + Mobile output',
    color: '#f59e0b',
    tags: ['RSS', 'Email', 'Mobile'],
  },
  {
    id: 'support',
    icon: '🤖',
    label: 'Customer Support',
    desc: 'API input → QA model → Web portal output',
    color: '#8b5cf6',
    tags: ['API', 'Web Portal', 'QA'],
  },
  {
    id: 'personal',
    icon: '🧠',
    label: 'Personal Assistant',
    desc: 'Multi-model routing with notifications and avatar',
    color: '#6366f1',
    tags: ['Multi-model', '3D Avatar', 'Notifications'],
  },
]

interface SetupWizardProps {
  onDismiss: () => void
}

export function SetupWizard({ onDismiss }: SetupWizardProps) {
  const [step, setStep] = useState<WizardStep>('welcome')
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)

  return (
    <motion.div
      className="absolute inset-0 z-30 flex items-center justify-center"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse at 50% 40%, rgba(6,10,26,0.92), rgba(5,9,20,0.98))',
          backdropFilter: 'blur(8px)',
        }}
      />

      {/* Content */}
      <div className="relative z-10 w-full max-w-2xl px-6">
        <AnimatePresence mode="wait">
          {step === 'welcome' && (
            <WelcomeStep
              key="welcome"
              onNext={() => setStep('template')}
              onSkip={onDismiss}
            />
          )}
          {step === 'template' && (
            <TemplateStep
              key="template"
              selected={selectedTemplate}
              onSelect={setSelectedTemplate}
              onNext={() => setStep('configure')}
              onBack={() => setStep('welcome')}
            />
          )}
          {step === 'configure' && (
            <ConfigureStep
              key="configure"
              template={TEMPLATES.find((t) => t.id === selectedTemplate)}
              onNext={() => setStep('activate')}
              onBack={() => setStep('template')}
            />
          )}
          {step === 'activate' && (
            <ActivateStep
              key="activate"
              onDone={onDismiss}
            />
          )}
        </AnimatePresence>

        {/* Progress dots */}
        <div className="flex justify-center gap-2 mt-8">
          {(['welcome', 'template', 'configure', 'activate'] as WizardStep[]).map((s) => (
            <div
              key={s}
              className="w-2 h-2 rounded-full transition-all duration-300"
              style={{
                backgroundColor: s === step ? '#00e5ff' : 'rgba(255,255,255,0.1)',
                boxShadow: s === step ? '0 0 8px rgba(0,229,255,0.5)' : 'none',
              }}
            />
          ))}
        </div>
      </div>
    </motion.div>
  )
}

// ── Steps ────────────────────────────────────────────────────────────────

function WelcomeStep({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  return (
    <motion.div
      className="text-center"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3 }}
    >
      {/* Offline tower icon */}
      <motion.div
        className="mx-auto w-24 h-24 rounded-full flex items-center justify-center mb-6"
        style={{
          background: 'radial-gradient(circle, rgba(239,68,68,0.12), rgba(8,10,25,0.95))',
          border: '1.5px solid rgba(239,68,68,0.2)',
          boxShadow: '0 0 40px rgba(239,68,68,0.1)',
        }}
        animate={{ scale: [1, 1.05, 1] }}
        transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
      >
        <span className="text-4xl">📡</span>
      </motion.div>

      <h1 className="text-2xl font-bold text-white/90 mb-2">
        Welcome to OllaBridge
      </h1>
      <p className="text-white/40 text-sm max-w-md mx-auto mb-2">
        AI Pipeline Builder + Control Tower
      </p>
      <p className="text-white/30 text-xs max-w-md mx-auto mb-8">
        Connect HomePilot personas, Ollama models, and consumer apps
        through a unified AI gateway. Let's get your system online.
      </p>

      <div className="flex gap-3 justify-center">
        <button
          onClick={onNext}
          className="px-6 py-3 rounded-xl text-sm font-semibold transition-all duration-200"
          style={{
            background: 'linear-gradient(135deg, rgba(0,229,255,0.2), rgba(139,92,246,0.2))',
            border: '1px solid rgba(0,229,255,0.3)',
            color: '#00e5ff',
            boxShadow: '0 0 20px rgba(0,229,255,0.1)',
          }}
        >
          Get Started
        </button>
        <button
          onClick={onSkip}
          className="px-6 py-3 rounded-xl text-sm text-white/30 hover:text-white/50 transition-colors"
          style={{
            border: '1px solid rgba(255,255,255,0.06)',
          }}
        >
          Skip Setup
        </button>
      </div>
    </motion.div>
  )
}

function TemplateStep({
  selected,
  onSelect,
  onNext,
  onBack,
}: {
  selected: string | null
  onSelect: (id: string) => void
  onNext: () => void
  onBack: () => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3 }}
    >
      <h2 className="text-xl font-bold text-white/90 text-center mb-1">
        Choose a Template
      </h2>
      <p className="text-white/35 text-xs text-center mb-6">
        Quick presets to get you started — you can customize everything later.
      </p>

      <div className="grid grid-cols-2 gap-3 mb-6">
        {TEMPLATES.map((tpl) => (
          <motion.button
            key={tpl.id}
            onClick={() => onSelect(tpl.id)}
            className="text-left p-4 rounded-xl transition-all"
            style={{
              background:
                selected === tpl.id
                  ? `linear-gradient(135deg, ${tpl.color}15, ${tpl.color}08)`
                  : 'linear-gradient(135deg, rgba(15,20,55,0.6), rgba(8,12,35,0.4))',
              border:
                selected === tpl.id
                  ? `1px solid ${tpl.color}40`
                  : '1px solid rgba(255,255,255,0.06)',
              boxShadow:
                selected === tpl.id
                  ? `0 0 20px ${tpl.color}10`
                  : 'none',
            }}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            <div className="flex items-center gap-3 mb-2">
              <span className="text-2xl">{tpl.icon}</span>
              <span className="text-sm font-semibold text-white/85">{tpl.label}</span>
            </div>
            <p className="text-xs text-white/35 mb-2">{tpl.desc}</p>
            <div className="flex gap-1.5 flex-wrap">
              {tpl.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider"
                  style={{
                    background: `${tpl.color}15`,
                    color: `${tpl.color}99`,
                    border: `1px solid ${tpl.color}25`,
                  }}
                >
                  {tag}
                </span>
              ))}
            </div>
          </motion.button>
        ))}
      </div>

      <div className="flex gap-3 justify-center">
        <button
          onClick={onBack}
          className="px-5 py-2.5 rounded-xl text-sm text-white/30 hover:text-white/50 transition-colors"
          style={{ border: '1px solid rgba(255,255,255,0.06)' }}
        >
          Back
        </button>
        <button
          onClick={onNext}
          disabled={!selected}
          className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 disabled:opacity-30"
          style={{
            background: 'linear-gradient(135deg, rgba(0,229,255,0.2), rgba(139,92,246,0.2))',
            border: '1px solid rgba(0,229,255,0.3)',
            color: '#00e5ff',
          }}
        >
          Continue
        </button>
      </div>
    </motion.div>
  )
}

function ConfigureStep({
  template,
  onNext,
  onBack,
}: {
  template?: Template
  onNext: () => void
  onBack: () => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3 }}
    >
      <h2 className="text-xl font-bold text-white/90 text-center mb-1">
        Configure {template?.label || 'Your Pipeline'}
      </h2>
      <p className="text-white/35 text-xs text-center mb-6">
        Verify these settings before activation. You can change them in Settings anytime.
      </p>

      <div className="glass-card p-5 mb-6 space-y-4">
        {/* HomePilot */}
        <ConfigItem
          label="HomePilot (LLM Source)"
          value="http://localhost:8000"
          hint="Persona-based AI backend"
          color="#14b8a6"
        />
        {/* Ollama */}
        <ConfigItem
          label="Ollama (LLM Source)"
          value="http://localhost:11434"
          hint="Local model inference"
          color="#00e5ff"
        />
        {/* Auth Mode */}
        <ConfigItem
          label="Auth Mode"
          value="pairing"
          hint="Device code exchange for clients"
          color="#f59e0b"
        />
        {/* Gateway */}
        <ConfigItem
          label="OllaBridge Gateway"
          value="http://localhost:11435"
          hint="Unified API endpoint"
          color="#8b5cf6"
        />
      </div>

      <div className="flex gap-3 justify-center">
        <button
          onClick={onBack}
          className="px-5 py-2.5 rounded-xl text-sm text-white/30 hover:text-white/50 transition-colors"
          style={{ border: '1px solid rgba(255,255,255,0.06)' }}
        >
          Back
        </button>
        <button
          onClick={onNext}
          className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200"
          style={{
            background: 'linear-gradient(135deg, rgba(20,184,166,0.25), rgba(0,229,255,0.2))',
            border: '1px solid rgba(20,184,166,0.4)',
            color: '#14b8a6',
          }}
        >
          Activate System
        </button>
      </div>
    </motion.div>
  )
}

function ConfigItem({
  label,
  value,
  hint,
  color,
}: {
  label: string
  value: string
  hint: string
  color: string
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/[0.04] last:border-0">
      <div>
        <div className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: color }}
          />
          <span className="text-sm text-white/70 font-medium">{label}</span>
        </div>
        <span className="text-[10px] text-white/30 ml-4">{hint}</span>
      </div>
      <code className="text-xs text-white/50 font-mono bg-white/5 px-2.5 py-1 rounded-lg">
        {value}
      </code>
    </div>
  )
}

function ActivateStep({ onDone }: { onDone: () => void }) {
  const [activating, setActivating] = useState(true)

  // Simulate activation
  useState(() => {
    const timer = setTimeout(() => setActivating(false), 2500)
    return () => clearTimeout(timer)
  })

  return (
    <motion.div
      className="text-center"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3 }}
    >
      {activating ? (
        <>
          <motion.div
            className="mx-auto w-24 h-24 rounded-full flex items-center justify-center mb-6"
            style={{
              background: 'radial-gradient(circle, rgba(0,229,255,0.15), rgba(8,10,25,0.95))',
              border: '1.5px solid rgba(0,229,255,0.25)',
              boxShadow: '0 0 40px rgba(0,229,255,0.15)',
            }}
            animate={{
              scale: [1, 1.1, 1],
              boxShadow: [
                '0 0 40px rgba(0,229,255,0.15)',
                '0 0 60px rgba(0,229,255,0.3)',
                '0 0 40px rgba(0,229,255,0.15)',
              ],
            }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
          >
            <span className="text-4xl">⚡</span>
          </motion.div>
          <h2 className="text-xl font-bold text-white/90 mb-2">
            Activating System...
          </h2>
          <p className="text-white/35 text-xs">
            Connecting to backends and initializing pipeline
          </p>
        </>
      ) : (
        <>
          <motion.div
            className="mx-auto w-24 h-24 rounded-full flex items-center justify-center mb-6"
            style={{
              background: 'radial-gradient(circle, rgba(20,184,166,0.15), rgba(8,10,25,0.95))',
              border: '1.5px solid rgba(20,184,166,0.3)',
              boxShadow: '0 0 40px rgba(20,184,166,0.15)',
            }}
            initial={{ scale: 0.8 }}
            animate={{ scale: 1 }}
            transition={{ type: 'spring', stiffness: 200, damping: 15 }}
          >
            <span className="text-4xl">✅</span>
          </motion.div>
          <h2 className="text-xl font-bold text-white/90 mb-2">
            System Ready
          </h2>
          <p className="text-white/35 text-xs mb-6">
            Your AI pipeline is configured. The dashboard will show live connections.
          </p>
          <button
            onClick={onDone}
            className="px-6 py-3 rounded-xl text-sm font-semibold transition-all duration-200"
            style={{
              background: 'linear-gradient(135deg, rgba(20,184,166,0.25), rgba(0,229,255,0.2))',
              border: '1px solid rgba(20,184,166,0.4)',
              color: '#14b8a6',
              boxShadow: '0 0 20px rgba(20,184,166,0.1)',
            }}
          >
            Open Dashboard
          </button>
        </>
      )}
    </motion.div>
  )
}
