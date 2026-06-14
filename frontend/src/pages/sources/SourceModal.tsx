import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  X,
  Eye,
  EyeOff,
  Loader2,
  CheckCircle2,
  XCircle,
  Lock,
  HardDrive,
  CloudUpload,
  ShieldCheck,
} from 'lucide-react'
import type {
  AvailableSource,
  SourceObject,
  SourceSharing,
  SourceStorageMode,
  SourceUpsertBody,
  SourceUpsertResponse,
} from '../../lib/api'
import { useUpsertSource } from '../../lib/hooks'
import { useToast } from './toast'

/** A source needs an explicit base_url before it can be configured. */
const BASE_URL_REQUIRED = new Set(['azure-openai', 'custom'])

type StorageOption = {
  value: SourceStorageMode
  label: string
  hint: string
  icon: typeof HardDrive
}

const STORAGE_OPTIONS: StorageOption[] = [
  { value: 'local_only', label: 'Local only', hint: 'Key never leaves this machine', icon: HardDrive },
  { value: 'cloud_encrypted_vault', label: 'Encrypted vault', hint: 'Sync key to your encrypted cloud vault', icon: CloudUpload },
  { value: 'organization_vault', label: 'Org vault', hint: 'Store key in your organization vault', icon: ShieldCheck },
]

const SHARING_OPTIONS: { value: SourceSharing; label: string; hint: string }[] = [
  { value: 'private', label: 'Private', hint: 'Only you' },
  { value: 'account', label: 'Account', hint: 'Your account' },
  { value: 'workspace', label: 'Workspace', hint: 'Your workspace' },
  { value: 'organization', label: 'Org', hint: 'Whole organization' },
]

export type ModalTarget =
  | { mode: 'add'; source: AvailableSource }
  | { mode: 'edit'; source: SourceObject }

type FormState = {
  display_name: string
  api_key: string
  base_url: string
  default_model: string
  storage_mode: SourceStorageMode
  sharing: SourceSharing
  allow_routing: boolean
}

function initialState(target: ModalTarget): FormState {
  if (target.mode === 'edit') {
    const s = target.source
    return {
      display_name: s.display_name ?? '',
      api_key: '',
      base_url: s.base_url ?? '',
      default_model: s.default_model ?? '',
      storage_mode: s.storage_mode,
      sharing: s.sharing,
      allow_routing: s.allow_routing,
    }
  }
  return {
    display_name: '',
    api_key: '',
    base_url: target.source.base_url ?? '',
    default_model: '',
    storage_mode: 'local_only',
    sharing: 'private',
    allow_routing: false,
  }
}

function fieldLabel(text: string) {
  return (
    <span className="block text-[11px] uppercase tracking-wider text-white/40 font-medium mb-1.5">
      {text}
    </span>
  )
}

export function SourceModal({
  target,
  onClose,
}: {
  target: ModalTarget
  onClose: () => void
}) {
  const name = target.source.name
  const label = target.source.label
  const isEdit = target.mode === 'edit'
  const baseUrlRequired = BASE_URL_REQUIRED.has(name)

  const [form, setForm] = useState<FormState>(() => initialState(target))
  const [showKey, setShowKey] = useState(false)
  const [testResult, setTestResult] = useState<SourceUpsertResponse['test'] | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)

  const upsert = useUpsertSource()
  const toast = useToast()
  const titleId = useId()
  const firstFieldRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  // Focus the first field on open.
  useEffect(() => {
    const t = setTimeout(() => firstFieldRef.current?.focus(), 50)
    return () => clearTimeout(t)
  }, [])

  // Esc to close + simple focus trap within the dialog.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key === 'Tab' && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])',
        )
        const list = Array.from(focusable).filter((el) => !el.hasAttribute('disabled'))
        if (list.length === 0) return
        const first = list[0]
        const last = list[list.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }))
    setValidationError(null)
  }

  const requiresKey = !isEdit || !target.source.key_configured
  const canSubmit = useMemo(() => {
    if (upsert.isPending) return false
    if (baseUrlRequired && !form.base_url.trim()) return false
    if (requiresKey && !form.api_key.trim()) return false
    return true
  }, [upsert.isPending, baseUrlRequired, form.base_url, form.api_key, requiresKey])

  async function handleSave() {
    if (baseUrlRequired && !form.base_url.trim()) {
      setValidationError(`Base URL is required for ${label}.`)
      return
    }
    if (requiresKey && !form.api_key.trim()) {
      setValidationError('An API key is required to add this source.')
      return
    }

    const body: SourceUpsertBody = {
      display_name: form.display_name.trim() || undefined,
      base_url: form.base_url.trim() || undefined,
      default_model: form.default_model.trim() || undefined,
      storage_mode: form.storage_mode,
      sharing: form.sharing,
      allow_routing: form.allow_routing,
    }
    if (form.api_key.trim()) body.api_key = form.api_key.trim()

    try {
      const res = await upsert.mutateAsync({ name, body })
      setForm((f) => ({ ...f, api_key: '' })) // never retain the key after save
      setShowKey(false)
      setTestResult(res.test)
      if (res.test) {
        if (res.test.ok) toast.success(`${label} connected — ${res.test.detail}`)
        else toast.error(`${label}: ${res.test.detail}`)
      } else {
        toast.success(`${label} saved`)
      }
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
        <div
          className="absolute inset-0 bg-navy-900/80 backdrop-blur-sm"
          onClick={onClose}
          aria-hidden
        />
        <motion.div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          initial={{ opacity: 0, y: 20, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 20, scale: 0.97 }}
          transition={{ type: 'spring', stiffness: 360, damping: 30 }}
          className="relative w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl border border-white/10 bg-navy-800/95 backdrop-blur-xl shadow-2xl"
        >
          {/* Header */}
          <div className="flex items-start justify-between gap-3 px-6 pt-6 pb-4 border-b border-white/5">
            <div>
              <h2 id={titleId} className="text-white font-bold text-lg">
                {isEdit ? `Configure ${label}` : `Add ${label}`}
              </h2>
              <p className="text-white/40 text-xs mt-0.5">
                {isEdit
                  ? 'Update settings. The key field is write-only.'
                  : 'Saved locally and tested. Keys never leave your control unless you opt in.'}
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>

          {/* Body */}
          <div className="px-6 py-5 space-y-4">
            {/* Provider (locked) */}
            <div>
              {fieldLabel('Provider')}
              <div className="w-full bg-navy-900/60 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white/70 flex items-center justify-between">
                <span>{label}</span>
                <span className="inline-flex items-center gap-1 text-[10px] text-white/30">
                  <Lock size={10} /> {isEdit ? 'locked' : name}
                </span>
              </div>
            </div>

            {/* Display name */}
            <div>
              {fieldLabel('Display name')}
              <input
                ref={firstFieldRef}
                type="text"
                value={form.display_name}
                onChange={(e) => set('display_name', e.target.value)}
                placeholder={`Personal ${label}`}
                className="w-full bg-navy-900/60 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
              />
            </div>

            {/* API key */}
            <div>
              {fieldLabel(isEdit ? 'API key (leave blank to keep current)' : 'API key')}
              <div className="relative">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={form.api_key}
                  onChange={(e) => set('api_key', e.target.value)}
                  placeholder={
                    isEdit && target.source.key_configured
                      ? target.source.key ?? '••••••••••••••'
                      : 'Paste your API key'
                  }
                  spellCheck={false}
                  autoComplete="off"
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
              <p className="text-[11px] text-white/30 mt-1.5 flex items-center gap-1">
                <Lock size={10} /> Stored encrypted; only a redacted hint is shown after saving.
              </p>
            </div>

            {/* Base URL */}
            <div>
              {fieldLabel(baseUrlRequired ? 'Base URL (required)' : 'Base URL')}
              <input
                type="text"
                value={form.base_url}
                onChange={(e) => set('base_url', e.target.value)}
                placeholder="https://api.example.com/v1"
                spellCheck={false}
                className="w-full bg-navy-900/60 border border-white/10 rounded-lg px-3 py-2.5 text-sm font-mono text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
              />
            </div>

            {/* Default model */}
            <div>
              {fieldLabel('Default model')}
              <input
                type="text"
                value={form.default_model}
                onChange={(e) => set('default_model', e.target.value)}
                placeholder="gpt-4o-mini"
                spellCheck={false}
                className="w-full bg-navy-900/60 border border-white/10 rounded-lg px-3 py-2.5 text-sm font-mono text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
              />
            </div>

            {/* Storage mode */}
            <div>
              {fieldLabel('Storage mode')}
              <div className="space-y-1.5">
                {STORAGE_OPTIONS.map((opt) => {
                  const Icon = opt.icon
                  const active = form.storage_mode === opt.value
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => set('storage_mode', opt.value)}
                      className="w-full flex items-center gap-3 px-3 py-2 rounded-lg border text-left transition-colors"
                      style={{
                        background: active ? 'rgba(0,229,255,0.08)' : 'rgba(255,255,255,0.02)',
                        borderColor: active ? 'rgba(0,229,255,0.35)' : 'rgba(255,255,255,0.08)',
                      }}
                    >
                      <span
                        className="w-3.5 h-3.5 rounded-full border-2 shrink-0"
                        style={{
                          borderColor: active ? '#00e5ff' : 'rgba(255,255,255,0.25)',
                          background: active
                            ? 'radial-gradient(circle, #00e5ff 0 40%, transparent 45%)'
                            : 'transparent',
                        }}
                      />
                      <Icon size={14} className={active ? 'text-glow-cyan' : 'text-white/40'} />
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm text-white/85">{opt.label}</span>
                        <span className="block text-[11px] text-white/35">{opt.hint}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Sharing */}
            <div>
              {fieldLabel('Sharing')}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                {SHARING_OPTIONS.map((opt) => {
                  const active = form.sharing === opt.value
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => set('sharing', opt.value)}
                      title={opt.hint}
                      className="px-2 py-2 rounded-lg border text-center transition-colors"
                      style={{
                        background: active ? 'rgba(139,92,246,0.12)' : 'rgba(255,255,255,0.02)',
                        borderColor: active ? 'rgba(139,92,246,0.4)' : 'rgba(255,255,255,0.08)',
                        color: active ? '#c4b5fd' : 'rgba(255,255,255,0.55)',
                      }}
                    >
                      <span className="block text-xs font-medium">{opt.label}</span>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Routing */}
            <label className="flex items-start gap-3 px-3 py-3 rounded-lg bg-navy-900/40 border border-white/8 cursor-pointer">
              <input
                type="checkbox"
                checked={form.allow_routing}
                onChange={(e) => set('allow_routing', e.target.checked)}
                className="mt-0.5 w-4 h-4 accent-[#00e5ff]"
              />
              <span>
                <span className="block text-sm text-white/85">Allow this source in routing</span>
                <span className="block text-[11px] text-white/35">
                  Off by default. When on, OllaBridge may pick this source under the active routing
                  profile.
                </span>
              </span>
            </label>

            {/* Validation */}
            {validationError && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs">
                <XCircle size={14} className="shrink-0 mt-0.5" />
                <span>{validationError}</span>
              </div>
            )}

            {/* Test result */}
            {testResult && (
              <div
                className="flex items-start gap-2 px-3 py-2.5 rounded-lg text-xs"
                style={{
                  background: testResult.ok ? 'rgba(20,184,166,0.1)' : 'rgba(239,68,68,0.1)',
                  border: `1px solid ${testResult.ok ? 'rgba(20,184,166,0.3)' : 'rgba(239,68,68,0.3)'}`,
                  color: testResult.ok ? '#5eead4' : '#fca5a5',
                }}
              >
                {testResult.ok ? (
                  <CheckCircle2 size={14} className="shrink-0 mt-0.5" />
                ) : (
                  <XCircle size={14} className="shrink-0 mt-0.5" />
                )}
                <span>
                  {testResult.ok ? 'Connected · ' : 'Test failed · '}
                  {testResult.detail}
                </span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-white/5">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm font-medium text-white/60 hover:text-white/90 hover:bg-white/5 transition-colors"
            >
              {testResult ? 'Close' : 'Cancel'}
            </button>
            <button
              onClick={handleSave}
              disabled={!canSubmit}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-glow-cyan/20 border border-glow-cyan/40 text-glow-cyan hover:bg-glow-cyan/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {upsert.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <CheckCircle2 size={14} />
              )}
              Save &amp; Test
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
