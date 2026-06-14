import { useEffect, useId, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { X, Eye, EyeOff, Loader2, KeyRound, Lock } from 'lucide-react'
import type { SourceObject } from '../../lib/api'
import { useRotateSource } from '../../lib/hooks'
import { useToast } from './toast'

export function RotateModal({
  source,
  onClose,
}: {
  source: SourceObject
  onClose: () => void
}) {
  const [key, setKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const rotate = useRotateSource()
  const toast = useToast()
  const titleId = useId()
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 50)
    return () => clearTimeout(t)
  }, [])

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  async function handleRotate() {
    if (!key.trim()) return
    try {
      const res = await rotate.mutateAsync({ name: source.name, api_key: key.trim() })
      setKey('')
      if (res.test?.ok) toast.success(`${source.label} key rotated — ${res.test.detail}`)
      else if (res.test) toast.error(`${source.label}: ${res.test.detail}`)
      else toast.success(`${source.label} key rotated`)
      onClose()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[150] flex items-center justify-center p-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <div className="absolute inset-0 bg-navy-900/80 backdrop-blur-sm" onClick={onClose} aria-hidden />
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          initial={{ opacity: 0, y: 20, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 20, scale: 0.97 }}
          transition={{ type: 'spring', stiffness: 360, damping: 30 }}
          className="relative w-full max-w-md rounded-2xl border border-white/10 bg-navy-800/95 backdrop-blur-xl shadow-2xl"
        >
          <div className="flex items-start justify-between gap-3 px-6 pt-6 pb-4 border-b border-white/5">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-amber-500/15 border border-amber-500/30">
                <KeyRound size={16} className="text-amber-400" />
              </div>
              <div>
                <h2 id={titleId} className="text-white font-bold text-base">
                  Rotate key
                </h2>
                <p className="text-white/40 text-xs">{source.display_name || source.label}</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>

          <div className="px-6 py-5 space-y-3">
            <p className="text-[12px] text-white/50 leading-relaxed">
              Replace the stored key. The new key is saved encrypted, tested, and the old one is
              discarded.
            </p>
            <div className="relative">
              <input
                ref={inputRef}
                type={showKey ? 'text' : 'password'}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="Paste the new API key"
                spellCheck={false}
                autoComplete="off"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleRotate()
                }}
                className="w-full bg-navy-900/60 border border-white/10 rounded-lg px-3 py-2.5 pr-10 text-sm font-mono text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-md text-white/40 hover:text-white/70 hover:bg-white/5 transition-colors"
                aria-label={showKey ? 'Hide key' : 'Show key'}
              >
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            <p className="text-[11px] text-white/30 flex items-center gap-1">
              <Lock size={10} /> Encrypted at rest. Never displayed after saving.
            </p>
          </div>

          <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-white/5">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm font-medium text-white/60 hover:text-white/90 hover:bg-white/5 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleRotate}
              disabled={!key.trim() || rotate.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-amber-500/20 border border-amber-500/40 text-amber-300 hover:bg-amber-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {rotate.isPending ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
              Rotate &amp; Test
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
