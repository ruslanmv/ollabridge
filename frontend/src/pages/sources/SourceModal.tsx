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
  Info,
  Globe,
  RefreshCw,
  ChevronRight,
} from 'lucide-react'
import type {
  AvailableSource,
  SourceExtraField,
  SourceObject,
  SourceSharing,
  SourceStorageMode,
  SourceUpsertBody,
  SourceUpsertResponse,
} from '../../lib/api'
import { useTestSource, useUpsertSource } from '../../lib/hooks'
import { useToast } from './toast'
import { ModelPicker } from './ModelPicker'
import { HeadersEditor } from './HeadersEditor'
import { headerCount, headerTextError } from './headers'
import { MoreDetails } from './ui'
import { splitProbeDetail } from './sourceStatus'
import { sourceUiProfile } from './sourceUiProfiles'

/** A source needs an explicit base_url before it can be configured. Some sources
 * declare the same requirement through their UI profile (requiresBaseUrl). */
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
  /** Provider-specific values, keyed by the backend field name. */
  extra: Record<string, string>
}

/**
 * The config fields this provider needs beyond a key, as declared by the
 * backend catalog. On edit they carry the current values; on add there is
 * nothing saved yet, so they start blank. Nothing here is provider-specific
 * in code — watsonx's project id arrives the same way any future field would.
 */
function extraFieldsOf(target: ModalTarget): SourceExtraField[] {
  if (target.mode === 'edit') return target.source.extra_fields ?? []
  return (target.source.extra_fields ?? []).map((f) => ({ ...f, value: '' }))
}

function initialState(target: ModalTarget): FormState {
  const extra = Object.fromEntries(
    extraFieldsOf(target).map((f) => [f.name, f.value ?? '']),
  )
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
      extra,
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
    extra,
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
  const profile = sourceUiProfile(name)
  const baseUrlRequired = BASE_URL_REQUIRED.has(name) || !!profile.requiresBaseUrl
  // Some providers name their credential something other than "API key"
  // (watsonx takes an IBM Cloud API key, not a watsonx-specific one).
  const credentialLabel = profile.credentialLabel ?? 'API key'

  const extraFields = useMemo(() => extraFieldsOf(target), [target])

  const [form, setForm] = useState<FormState>(() => initialState(target))
  // What the backend holds, as this form last saw it. A test runs against
  // the saved settings, so it is offered only while the form matches them.
  const [saved, setSaved] = useState<FormState | null>(() =>
    target.mode === 'edit' ? initialState(target) : null,
  )
  const hasUnsavedChanges =
    saved === null ||
    form.api_key.trim() !== '' ||
    JSON.stringify({ ...form, api_key: '' }) !== JSON.stringify(saved)

  // Whether the model list can be fetched at all. The backend's flag is
  // authoritative — the UI profile is only a hint for providers the catalog
  // has not been asked about yet.
  const canDiscover =
    target.source.supports_discovery ?? profile.supportsDiscovery ?? false
  // Discovery needs a saved key, so it only becomes possible after the first
  // successful save. `keySaved` tracks that within this dialog's lifetime.
  const [keySaved, setKeySaved] = useState(
    () => target.mode === 'edit' && target.source.key_configured,
  )
  const suggested = target.source.suggested_models ?? []

  // Warn on an unencrypted connection to a non-local host.
  const isRemoteHttp = useMemo(() => {
    const u = form.base_url.trim().toLowerCase()
    return (
      u.startsWith('http://') &&
      !u.startsWith('http://localhost') &&
      !u.startsWith('http://127.0.0.1') &&
      !u.startsWith('http://[::1]')
    )
  }, [form.base_url])
  const [showKey, setShowKey] = useState(false)
  const [testResult, setTestResult] = useState<SourceUpsertResponse['test'] | null>(null)
  const [discovery, setDiscovery] = useState<SourceUpsertResponse['discovery'] | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)

  const upsert = useUpsertSource()
  const test = useTestSource()
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

  const setExtra = (field: string, value: string) => {
    setForm((f) => ({ ...f, extra: { ...f.extra, [field]: value } }))
    setValidationError(null)
  }

  // Which optional (advanced) fields the user has expanded. Collapsed by default.
  const [openAdvanced, setOpenAdvanced] = useState<Record<string, boolean>>({})

  /** Per-field problems the backend would refuse on save, checked as you type. */
  const extraErrors = useMemo(() => {
    const errors: Record<string, string> = {}
    for (const f of extraFields) {
      const error = f.widget === 'headers' ? headerTextError(form.extra[f.name] ?? '') : null
      if (error) errors[f.name] = error
    }
    return errors
  }, [extraFields, form.extra])

  /** The input for one catalog-declared field, with its help lines. */
  function renderExtraField(field: SourceExtraField) {
    const value = form.extra[field.name] ?? ''
    const isMissing = field.required && !value.trim()
    return (
      <>
        {field.widget === 'headers' ? (
          <HeadersEditor
            value={value}
            onChange={(text) => setExtra(field.name, text)}
            placeholder={field.placeholder}
          />
        ) : (
          <input
            type="text"
            value={value}
            onChange={(e) => setExtra(field.name, e.target.value)}
            placeholder={field.placeholder || field.label}
            spellCheck={false}
            autoComplete="off"
            aria-label={field.label}
            aria-required={field.required}
            aria-invalid={isMissing}
            className="w-full bg-navy-900/60 border rounded-lg px-3 py-2.5 text-sm font-mono text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
            style={{
              borderColor: isMissing ? 'rgba(245,158,11,0.4)' : 'rgba(255,255,255,0.1)',
            }}
          />
        )}
        {field.help && <p className="text-[11px] text-white/30 mt-1.5">{field.help}</p>}
        {field.env_var && (
          <p className="text-[11px] text-white/25 mt-1">
            Falls back to <span className="font-mono">{field.env_var}</span> when left blank.
          </p>
        )}
      </>
    )
  }

  /** Required provider config the form is still missing. */
  const missingExtras = useMemo(
    () => extraFields.filter((f) => f.required && !form.extra[f.name]?.trim()),
    [extraFields, form.extra],
  )

  const requiresKey = !isEdit || !target.source.key_configured
  const busy = upsert.isPending || test.isPending
  // The verdict leads; the provider's long reason sits behind "Details".
  const probe = testResult ? splitProbeDetail(testResult.detail) : null
  const canTest = keySaved && !hasUnsavedChanges && !busy
  const canSubmit = useMemo(() => {
    if (upsert.isPending || test.isPending) return false
    if (baseUrlRequired && !form.base_url.trim()) return false
    if (requiresKey && !form.api_key.trim()) return false
    if (missingExtras.length > 0) return false
    if (Object.keys(extraErrors).length > 0) return false
    return true
  }, [
    upsert.isPending,
    test.isPending,
    baseUrlRequired,
    form.base_url,
    form.api_key,
    requiresKey,
    missingExtras,
    extraErrors,
  ])

  async function handleSave() {
    if (baseUrlRequired && !form.base_url.trim()) {
      setValidationError(`Base URL is required for ${label}.`)
      return
    }
    if (requiresKey && !form.api_key.trim()) {
      setValidationError('An API key is required to add this source.')
      return
    }
    if (missingExtras.length > 0) {
      const labels = missingExtras.map((f) => f.label).join(', ')
      setValidationError(`${labels} ${missingExtras.length === 1 ? 'is' : 'are'} required for ${label}.`)
      return
    }
    const firstExtraError = Object.values(extraErrors)[0]
    if (firstExtraError) {
      setValidationError(firstExtraError)
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
    // Send every declared field, trimmed. A blank one clears the stored
    // value, which is how the user removes an optional field.
    if (extraFields.length > 0) {
      body.extra = Object.fromEntries(
        extraFields.map((f) => [f.name, (form.extra[f.name] ?? '').trim()]),
      )
    }

    try {
      const res = await upsert.mutateAsync({ name, body })
      // Never retain the key after save. Show whichever default model the
      // backend settled on, so a source saved with the field blank does not
      // read as "no model" when it has in fact been given a free one.
      // Read extra fields back as stored: the backend normalizes some (pasted
      // JSON headers come back as plain lines). A field with an env fallback
      // keeps what was typed — its echoed value may be the env var's, which
      // the next save would otherwise write in as the source's own.
      const stored = new Map(
        (res.source.extra_fields ?? [])
          .filter((f) => !f.env_var)
          .map((f) => [f.name, f.value ?? ''] as const),
      )
      const next = {
        ...form,
        api_key: '',
        default_model: res.source.default_model ?? form.default_model,
        extra: Object.fromEntries(
          Object.entries(form.extra).map(([k, v]) => [k, stored.get(k) ?? v]),
        ),
      }
      setForm(next)
      setSaved(next)
      setShowKey(false)
      setKeySaved(res.source.key_configured)
      setTestResult(res.test)
      setDiscovery(res.discovery ?? null)
      // The settings are stored whatever the connection check says, so the
      // toast reports the save; a failed check stays in the panel below,
      // where Test connection can retry it once the provider side is fixed.
      if (res.test && !res.test.ok) {
        toast.success(`${label} saved — the connection test failed, see below`)
      } else {
        toast.success(`${label} saved`)
      }
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  /** Probe the saved settings and reload the model list from them. */
  async function handleTest() {
    try {
      const res = await test.mutateAsync(name)
      setTestResult({ ok: res.ok, detail: res.detail })
      if (res.ok) toast.success(`${label} connected — ${res.detail}`)
      else toast.error(`${label}: ${res.detail}`)
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
              {fieldLabel(
                isEdit
                  ? `${credentialLabel} (leave blank to keep current)`
                  : credentialLabel,
              )}
              <div className="relative">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={form.api_key}
                  onChange={(e) => set('api_key', e.target.value)}
                  placeholder={
                    isEdit && target.source.key_configured
                      ? target.source.key ?? '••••••••••••••'
                      : profile.credentialPlaceholder ?? `Paste your ${credentialLabel.toLowerCase()}`
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

            {/* Provider-specific config (e.g. watsonx project id). Declared by
                the backend catalog, so no provider is named in code here. */}
            {extraFields
              .filter((field) => !field.advanced)
              .map((field) => (
                <div key={field.name}>
                  {fieldLabel(field.required ? `${field.label} (required)` : field.label)}
                  {renderExtraField(field)}
                </div>
              ))}

            {/* Base URL */}
            <div>
              {fieldLabel(baseUrlRequired ? 'Server URL (required)' : 'Base URL')}
              <input
                type="text"
                value={form.base_url}
                onChange={(e) => set('base_url', e.target.value)}
                placeholder={profile.baseUrlPlaceholder ?? 'https://api.example.com/v1'}
                spellCheck={false}
                className="w-full bg-navy-900/60 border border-white/10 rounded-lg px-3 py-2.5 text-sm font-mono text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
              />
              {isRemoteHttp && (
                <p className="text-[11px] text-amber-300/80 mt-1.5">
                  This remote connection is not encrypted. Use HTTPS.
                </p>
              )}
            </div>

            {/* Optional, rarely needed config (custom headers): collapsed until
                asked for, with a count so a configured value is never hidden
                silently. */}
            {extraFields
              .filter((field) => field.advanced)
              .map((field) => {
                // A field with a problem stays open: Save is blocked on it,
                // and a hidden reason would be no reason at all.
                const open = (openAdvanced[field.name] ?? false) || !!extraErrors[field.name]
                const panelId = `${titleId}-${field.name}`
                const value = form.extra[field.name] ?? ''
                const count = field.widget === 'headers' ? headerCount(value) : value.trim() ? 1 : 0
                return (
                  <div key={field.name} className="rounded-lg border border-white/8 bg-navy-900/30">
                    <button
                      type="button"
                      aria-expanded={open}
                      aria-controls={panelId}
                      // While an error holds it open, a click must not queue a
                      // collapse that would fire the moment the error is fixed.
                      title={extraErrors[field.name] ? 'Fix the highlighted entry first' : undefined}
                      onClick={() => {
                        if (extraErrors[field.name]) return
                        setOpenAdvanced((o) => ({ ...o, [field.name]: !open }))
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-white/[0.03] transition-colors rounded-lg"
                    >
                      <ChevronRight
                        size={14}
                        className={`text-white/40 transition-transform ${open ? 'rotate-90' : ''}`}
                      />
                      <span className="text-sm text-white/80">{field.label}</span>
                      <span className="text-[10px] uppercase tracking-wider text-white/30">
                        Optional
                      </span>
                      {count > 0 && (
                        <span className="ml-auto px-1.5 py-0.5 rounded text-[10px] font-medium bg-glow-cyan/10 text-glow-cyan/80 border border-glow-cyan/20">
                          {field.widget === 'headers'
                            ? `${count} header${count === 1 ? '' : 's'}`
                            : 'Set'}
                        </span>
                      )}
                    </button>
                    {open && (
                      <div id={panelId} className="px-3 pb-3">
                        {renderExtraField(field)}
                      </div>
                    )}
                  </div>
                )
              })}

            {/* Setup hint + remote-source notice (from the source UI profile) */}
            {profile.setupHint && (
              <p className="text-[11px] text-white/40 flex items-start gap-1.5">
                <Info size={12} className="shrink-0 mt-0.5" /> {profile.setupHint}
              </p>
            )}
            {profile.showRemoteNotice && (
              <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-amber-500/10 border border-amber-500/25 text-amber-200/90 text-[11px]">
                <Globe size={13} className="shrink-0 mt-0.5" />
                <span>
                  <span className="font-semibold">Remote AI source.</span> Prompts sent through this
                  source are processed by the configured remote server.
                </span>
              </div>
            )}

            {/* Default model — typed, or picked from the source's live catalog */}
            <div>
              {fieldLabel('Default model')}
              <input
                type="text"
                value={form.default_model}
                onChange={(e) => set('default_model', e.target.value)}
                placeholder={
                  suggested[0] ?? profile.defaultModelPlaceholder ?? 'gpt-4o-mini'
                }
                spellCheck={false}
                className="w-full bg-navy-900/60 border border-white/10 rounded-lg px-3 py-2.5 text-sm font-mono text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors"
              />
              <p className="text-[11px] text-white/30 mt-1.5">
                {suggested.length > 0
                  ? `Leave blank to use a free model — ${suggested[0]} when your key can reach it.`
                  : canDiscover
                    ? 'Leave blank and the best model your key can reach is chosen for you.'
                    : 'Used when a request does not pin a model.'}
              </p>
              {canDiscover && (
                <div className="mt-2">
                  <ModelPicker
                    name={name}
                    enabled={keySaved}
                    value={form.default_model}
                    onSelect={(id) => set('default_model', id)}
                  />
                </div>
              )}
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
                <span className="min-w-0">
                  {testResult.ok ? 'Connected · ' : 'Test failed · '}
                  {probe?.summary}
                  {probe?.reason && <MoreDetails text={probe.reason} />}
                </span>
              </div>
            )}

            {/* Discovery summary — real counts of the models this key can access. */}
            {discovery && (
              <div className="px-3 py-2.5 rounded-lg bg-glow-cyan/5 border border-glow-cyan/20 text-xs text-white/70">
                <div className="font-semibold text-white/90">
                  {discovery.count} accessible model{discovery.count === 1 ? '' : 's'} discovered
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-white/50">
                  {Object.entries(discovery.connection_types).map(([k, n]) => (
                    <span key={k}>{n} {k}</span>
                  ))}
                  {discovery.free !== undefined && (
                    <span className="text-teal-300/80">{discovery.free} free</span>
                  )}
                  <span>{discovery.persona_compatible} persona-compatible</span>
                </div>
                {discovery.count === 0 && (
                  <p className="mt-1.5 text-white/45">
                    Connected, but no models are visible to this key’s user. Confirm the user has
                    access to at least one model.
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Footer — save first, then test: the test and the model list
              both run against what is saved, never against unsaved edits. */}
          <div className="px-6 py-4 border-t border-white/5">
            {!canTest && !busy && (
              <p className="text-[11px] text-white/35 text-right mb-2">
                {keySaved
                  ? 'Save your changes, then test the connection.'
                  : 'Save first — the test and the model list use the saved key.'}
              </p>
            )}
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={onClose}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white/60 hover:text-white/90 hover:bg-white/5 transition-colors"
              >
                {hasUnsavedChanges ? 'Cancel' : 'Close'}
              </button>
              <button
                onClick={handleTest}
                disabled={!canTest}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-white/15 text-white/75 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {test.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <RefreshCw size={14} />
                )}
                Test connection
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
                {isEdit ? 'Save' : (profile.connectLabel ?? 'Save')}
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
