import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, XCircle, Info, X } from 'lucide-react'

type ToastKind = 'success' | 'error' | 'info'
type Toast = { id: number; kind: ToastKind; message: string }

type ToastApi = {
  push: (kind: ToastKind, message: string) => void
  success: (message: string) => void
  error: (message: string) => void
  info: (message: string) => void
}

const ToastCtx = createContext<ToastApi | null>(null)

const TONE: Record<ToastKind, { color: string; icon: typeof CheckCircle2 }> = {
  success: { color: '#14b8a6', icon: CheckCircle2 },
  error: { color: '#ef4444', icon: XCircle },
  info: { color: '#00e5ff', icon: Info },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const remove = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id))
  }, [])

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = Date.now() + Math.random()
      setToasts((t) => [...t, { id, kind, message }])
      setTimeout(() => remove(id), 5000)
    },
    [remove],
  )

  const apiValue: ToastApi = {
    push,
    success: (m) => push('success', m),
    error: (m) => push('error', m),
    info: (m) => push('info', m),
  }

  return (
    <ToastCtx.Provider value={apiValue}>
      {children}
      <div className="fixed bottom-6 right-6 z-[200] flex flex-col gap-2 w-[360px] max-w-[calc(100vw-3rem)]">
        <AnimatePresence>
          {toasts.map((t) => {
            const tone = TONE[t.kind]
            const Icon = tone.icon
            return (
              <motion.div
                key={t.id}
                layout
                initial={{ opacity: 0, x: 40, scale: 0.96 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0, x: 40, scale: 0.96 }}
                transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                className="flex items-start gap-3 px-4 py-3 rounded-xl border backdrop-blur-xl shadow-2xl"
                style={{
                  background: 'linear-gradient(135deg, rgba(15,20,55,0.92), rgba(10,14,40,0.88))',
                  borderColor: `${tone.color}40`,
                }}
              >
                <Icon size={16} style={{ color: tone.color }} className="shrink-0 mt-0.5" />
                <span className="flex-1 text-sm text-white/85 leading-snug break-words">{t.message}</span>
                <button
                  onClick={() => remove(t.id)}
                  className="shrink-0 text-white/30 hover:text-white/70 transition-colors"
                  aria-label="Dismiss"
                >
                  <X size={14} />
                </button>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  )
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
