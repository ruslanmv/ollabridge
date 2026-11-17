/**
 * Model copies: an installed model under a new name with its own context window.
 *
 *   ModelCopiesSection   the table on Model Inventory: model, built from, context, loads here
 *   BuildModelWizard     three steps: pick a model, pick a context size, create and test
 *
 * A copy shares the original's files (no download, no extra disk space). Whether it
 * loads depends on the memory free on this machine, so "Loads here" is measured:
 * the gateway loads the model once and records the answer.
 */
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Check, CopyPlus, Layers, Loader2, Play, Trash2, X } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { useBuildVariant, useModelVariants, useRemoveVariant, useTestVariant } from '../../lib/localHooks'
import type { ModelLoadResult, ModelVariant } from '../../lib/localApi'
import { formatBytes, normalizeRef } from './modelRefs'

const CYAN = '#00e5ff'
const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*(:[A-Za-z0-9._-]+)?$/
const KIND_LABEL: Record<ModelVariant['kind'], string> = {
  chat: 'Chat',
  decision: 'Decision',
  embedding: 'Embedding',
}

/** `request()` prefixes errors with the method and path; a person needs only the reason. */
function errorText(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  const cut = message.indexOf(' — ')
  return cut >= 0 ? message.slice(cut + 3) : message
}

function sizeLabel(context: number): string {
  return context % 1024 === 0 ? `${context / 1024}K` : context.toLocaleString()
}

/** Mirrors the gateway's `suggest_name`: `clef-flash:9b` at 6144 becomes `clef-flash-6k`. */
function suggestName(source: string, context: number): string {
  const base = (source.split('/').pop() ?? source).split(':')[0].replace(/-\d+k?$/i, '')
  return `${base}-${context % 1024 === 0 ? `${context / 1024}k` : context}`
}

/** The model a copy shares its files with; an original is its own root. */
function rootOf(model: ModelVariant): string {
  return model.is_copy && model.built_from ? model.built_from : model.name
}

function memoryText(load: ModelLoadResult): string {
  if (!load.total_bytes) return ''
  const gpu = load.gpu_bytes ? `, ${formatBytes(load.gpu_bytes)} on the GPU` : ', none on the GPU'
  return `${formatBytes(load.total_bytes)} of memory${gpu}`
}

// ── The table ────────────────────────────────────────────────────────────

export function ModelCopiesSection({ onChanged }: { onChanged: () => void }) {
  const { data, isLoading, error } = useModelVariants()
  const test = useTestVariant()
  const remove = useRemoveVariant()
  const [wizard, setWizard] = useState<{ source?: string } | null>(null)
  const models = data?.models ?? []
  const testing = test.isPending ? test.variables : null

  return (
    <motion.div className="glass-card overflow-hidden" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
      <div className="flex items-center justify-between gap-4 px-6 py-4 border-b border-white/[0.06]">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: `${CYAN}15`, border: `1px solid ${CYAN}30`, color: CYAN }}
          >
            <Layers size={16} />
          </div>
          <div className="min-w-0">
            <span className="text-white/85 font-semibold text-sm">Model copies</span>
            <p className="text-[11px] text-white/35 mt-0.5">
              A copy is an installed model with its own context window. It shares the original's files, so it takes
              no extra disk space.
            </p>
          </div>
        </div>
        <motion.button
          onClick={() => setWizard({})}
          disabled={models.length === 0}
          className="flex shrink-0 items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: 'linear-gradient(135deg, rgba(0,229,255,0.15), rgba(139,92,246,0.15))',
            border: '1px solid rgba(0,229,255,0.25)',
            color: CYAN,
          }}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
        >
          <CopyPlus size={15} />
          Build a model
        </motion.button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-white/40">
          <Loader2 size={15} className="animate-spin" /> Reading installed models...
        </div>
      ) : error ? (
        <p className="px-6 py-6 text-sm text-amber-300/80">{errorText(error)}</p>
      ) : models.length === 0 ? (
        <p className="px-6 py-8 text-center text-sm text-white/35">
          No models installed yet. Download one with "Get models", then build copies of it here.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-white/30">
                <th className="px-6 py-2.5 font-medium">Model</th>
                <th className="px-3 py-2.5 font-medium">Built from</th>
                <th className="px-3 py-2.5 font-medium text-right">Context</th>
                <th className="px-3 py-2.5 font-medium">Loads here</th>
                <th className="px-6 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {models.map((model) => (
                <tr key={model.name} className="border-t border-white/[0.05] hover:bg-white/[0.02]">
                  <td className="px-6 py-3">
                    <span className={`font-mono text-white/80 ${model.is_copy ? 'pl-4' : ''}`}>{model.name}</span>
                    <span className="ml-2 text-[10px] text-white/30">
                      {KIND_LABEL[model.kind]}
                      {!model.is_copy && model.size_bytes ? ` · ${formatBytes(model.size_bytes)}` : ''}
                    </span>
                  </td>
                  <td className="px-3 py-3 font-mono text-xs text-white/45">{model.built_from ?? '—'}</td>
                  <td className="px-3 py-3 text-right tabular-nums text-white/70">
                    {model.context ? model.context.toLocaleString() : <span className="text-white/35">Default</span>}
                  </td>
                  <td className="px-3 py-3">
                    <LoadBadge load={model.load} testing={testing === model.name} />
                  </td>
                  <td className="px-6 py-3">
                    <div className="flex items-center justify-end gap-1.5">
                      <RowButton
                        title="Load it once to see whether it fits on this machine"
                        disabled={test.isPending}
                        onClick={() => test.mutate(model.name)}
                      >
                        <Play size={12} /> Test
                      </RowButton>
                      <RowButton title="Make a copy with another context window" onClick={() => setWizard({ source: model.name })}>
                        <CopyPlus size={12} /> Copy
                      </RowButton>
                      {model.is_copy && (
                        <RowButton
                          title="Remove this copy. The original stays."
                          disabled={remove.isPending}
                          onClick={() => {
                            if (window.confirm(`Remove ${model.name}? ${model.built_from} stays installed.`)) {
                              remove.mutate(model.name, { onSuccess: onChanged })
                            }
                          }}
                        >
                          <Trash2 size={12} />
                        </RowButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(test.isError || remove.isError) && (
        <p className="border-t border-white/[0.05] px-6 py-3 text-xs text-red-300">
          {errorText(test.error ?? remove.error)}
        </p>
      )}

      {wizard && (
        <BuildModelWizard
          models={models}
          presets={data?.presets ?? []}
          initialSource={wizard.source}
          onClose={() => setWizard(null)}
          onChanged={onChanged}
        />
      )}
    </motion.div>
  )
}

function RowButton({
  children,
  onClick,
  disabled,
  title,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  title: string
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] text-white/60 transition-colors hover:bg-white/[0.08] hover:text-white/85 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  )
}

function LoadBadge({ load, testing }: { load: ModelLoadResult | null; testing: boolean }) {
  if (testing) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-white/55">
        <Loader2 size={12} className="animate-spin" style={{ color: CYAN }} /> Loading it...
      </span>
    )
  }
  if (!load) return <span className="text-xs text-white/30">Not tested</span>
  const when = new Date(load.tested_at).toLocaleString()
  if (load.loads) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-emerald-300" title={`Tested ${when}`}>
        <Check size={12} /> Yes
        <span className="text-white/35">{memoryText(load)}</span>
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-amber-300" title={`Tested ${when}`}>
      <AlertTriangle size={12} /> No
      <span className="text-white/35">{load.reason}</span>
    </span>
  )
}

// ── The wizard ───────────────────────────────────────────────────────────

type Step = 'model' | 'context' | 'result'
const RAIL: { step: Step; label: string }[] = [
  { step: 'model', label: 'Model' },
  { step: 'context', label: 'Context size' },
  { step: 'result', label: 'Create and test' },
]

export function BuildModelWizard({
  models,
  presets,
  initialSource,
  onClose,
  onChanged,
}: {
  models: ModelVariant[]
  presets: number[]
  /** Opened from a row: the model is chosen already. */
  initialSource?: string
  onClose: () => void
  onChanged: () => void
}) {
  const titleId = useId()
  const build = useBuildVariant()
  const test = useTestVariant()
  const [step, setStep] = useState<Step>(initialSource ? 'context' : 'model')
  const [source, setSource] = useState(initialSource ?? '')
  const [context, setContext] = useState<number | null>(null)
  const [customContext, setCustomContext] = useState('')
  const [name, setName] = useState('')
  const [nameEdited, setNameEdited] = useState(false)
  const [result, setResult] = useState<ModelVariant | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const busy = build.isPending || test.isPending
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && !busy && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const origin = models.find((model) => normalizeRef(model.name) === normalizeRef(source)) ?? null
  const root = origin ? rootOf(origin) : ''
  const siblings = models.filter((model) => model.is_copy && model.built_from === root)
  const sizes = presets.filter((size) => !origin?.max_context || size <= origin.max_context)
  const finalName = nameEdited ? name.trim() : context && origin ? suggestName(root, context) : ''
  const existing = models.find((model) => normalizeRef(model.name) === normalizeRef(finalName)) ?? null
  const tooLarge = !!(context && origin?.max_context && context > origin.max_context)
  const ready = !!origin && !!context && context >= 512 && !tooLarge && NAME_PATTERN.test(finalName)

  /** Create the copy (unless that name exists already) and load it once. */
  function run(size: number, copyName: string, alreadyThere: boolean) {
    setStep('result')
    setResult(null)
    setFailure(null)
    const loadIt = (target: string) =>
      test.mutate(target, {
        onSuccess: setResult,
        onError: (error) => setFailure(errorText(error)),
      })
    if (alreadyThere) {
      loadIt(copyName)
      return
    }
    build.mutate(
      { source, context: size, name: copyName },
      {
        onSuccess: (created) => {
          onChanged()
          loadIt(created.name)
        },
        onError: (error) => setFailure(errorText(error)),
      },
    )
  }

  function trySmaller(size: number) {
    const smallerName = suggestName(root, size)
    setContext(size)
    setCustomContext('')
    setNameEdited(false)
    run(size, smallerName, models.some((model) => normalizeRef(model.name) === normalizeRef(smallerName)))
  }

  const railIndex = RAIL.findIndex((item) => item.step === step)

  // In a portal: the card that hosts the table clips and re-anchors a fixed child.
  return createPortal(
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[150] flex items-center justify-center p-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <div
          className="absolute inset-0 bg-navy-900/80 backdrop-blur-sm"
          onClick={() => !busy && onClose()}
          aria-hidden
        />
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          initial={{ opacity: 0, y: 20, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ type: 'spring', stiffness: 360, damping: 30 }}
          className="relative flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-navy-800/95 shadow-2xl backdrop-blur-xl"
        >
          {/* header */}
          <div className="flex items-start justify-between gap-3 border-b border-white/5 px-6 pb-4 pt-6">
            <div className="flex items-center gap-3">
              <div
                className="flex h-10 w-10 items-center justify-center rounded-xl"
                style={{ background: `linear-gradient(135deg, ${CYAN}22, ${CYAN}08)`, border: `1px solid ${CYAN}30` }}
              >
                <CopyPlus size={18} style={{ color: CYAN }} />
              </div>
              <div>
                <h2 id={titleId} className="text-base font-bold text-white">
                  Build a model
                </h2>
                <p className="text-xs text-white/40">A copy of a model you already have, sized for this machine</p>
              </div>
            </div>
            <button
              onClick={onClose}
              disabled={busy}
              className="rounded-lg p-1.5 text-white/40 transition-colors hover:bg-white/5 hover:text-white/80 disabled:opacity-30"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>

          {/* step rail */}
          <ol className="flex items-center gap-2 border-b border-white/5 px-6 py-4">
            {RAIL.map((item, index) => {
              const done = index < railIndex
              const active = index === railIndex
              return (
                <li key={item.step} className="flex min-w-0 flex-1 items-center gap-2">
                  <span
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
                    style={{
                      background: done ? `${CYAN}26` : active ? `${CYAN}14` : 'rgba(255,255,255,0.04)',
                      border: `1px solid ${done || active ? `${CYAN}60` : 'rgba(255,255,255,0.1)'}`,
                      color: done || active ? CYAN : 'rgba(255,255,255,0.35)',
                    }}
                  >
                    {done ? <Check size={12} /> : index + 1}
                  </span>
                  <span
                    className={`truncate text-xs font-medium ${
                      active ? 'text-white/90' : done ? 'text-white/60' : 'text-white/35'
                    }`}
                  >
                    {item.label}
                  </span>
                </li>
              )
            })}
          </ol>

          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {step === 'model' && (
              <div className="space-y-3">
                <p className="text-sm text-white/70">Which model do you want to copy?</p>
                <div className="space-y-1.5" role="radiogroup" aria-label="Installed models">
                  {models.map((model) => {
                    const selected = normalizeRef(model.name) === normalizeRef(source)
                    return (
                      <button
                        key={model.name}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => {
                          setSource(model.name)
                          setContext(null)
                          setNameEdited(false)
                        }}
                        className="flex w-full items-center justify-between gap-3 rounded-xl border px-4 py-2.5 text-left transition-colors"
                        style={{
                          background: selected ? `${CYAN}10` : 'rgba(255,255,255,0.03)',
                          borderColor: selected ? `${CYAN}55` : 'rgba(255,255,255,0.08)',
                        }}
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-mono text-sm text-white/85">{model.name}</span>
                          <span className="text-[11px] text-white/35">
                            {KIND_LABEL[model.kind]}
                            {model.parameter_size ? ` · ${model.parameter_size}` : ''}
                            {model.is_copy ? ` · copy of ${model.built_from}` : ''}
                          </span>
                        </span>
                        <span className="shrink-0 text-right text-[11px] text-white/40">
                          {model.context ? `${model.context.toLocaleString()} tokens` : 'Default context'}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {step === 'context' && origin && (
              <div className="space-y-4">
                <div>
                  <p className="text-sm text-white/70">
                    How much context should <span className="font-mono text-white/90">{root}</span> run with?
                  </p>
                  <p className="mt-1 text-xs leading-relaxed text-white/40">
                    The context window is how much text the model can read at once. A smaller window needs less
                    memory, so pick a smaller one if the model does not load.
                    {origin.max_context ? ` This model supports up to ${origin.max_context.toLocaleString()} tokens.` : ''}
                  </p>
                </div>
                <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Context size">
                  {sizes.map((size) => {
                    const selected = context === size && !customContext
                    const tried = siblings.find((model) => model.context === size)
                    return (
                      <button
                        key={size}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => {
                          setContext(size)
                          setCustomContext('')
                        }}
                        className="rounded-xl border px-3 py-2.5 text-left transition-colors"
                        style={{
                          background: selected ? `${CYAN}10` : 'rgba(255,255,255,0.03)',
                          borderColor: selected ? `${CYAN}55` : 'rgba(255,255,255,0.08)',
                        }}
                      >
                        <span className="block text-sm font-semibold text-white/85">{sizeLabel(size)}</span>
                        <span className="block text-[11px] text-white/35">{size.toLocaleString()} tokens</span>
                        {tried?.load && (
                          <span className={`mt-1 block text-[11px] ${tried.load.loads ? 'text-emerald-300' : 'text-amber-300'}`}>
                            {tried.load.loads ? 'Loads here' : 'Did not load'}
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
                <label className="block text-[11px] uppercase tracking-wider text-white/30">
                  Another size, in tokens
                  <input
                    inputMode="numeric"
                    value={customContext}
                    onChange={(event) => {
                      const digits = event.target.value.replace(/\D/g, '')
                      setCustomContext(digits)
                      setContext(digits ? Number(digits) : null)
                    }}
                    placeholder="for example 5000"
                    className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm normal-case tracking-normal text-white/85 placeholder:text-white/25 focus:border-glow-cyan/50 focus:outline-none"
                  />
                </label>
                <label className="block text-[11px] uppercase tracking-wider text-white/30">
                  Name of the copy
                  <input
                    value={finalName}
                    onChange={(event) => {
                      setNameEdited(true)
                      setName(event.target.value)
                    }}
                    placeholder="pick a size first"
                    className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 font-mono text-sm normal-case tracking-normal text-white/85 placeholder:text-white/25 focus:border-glow-cyan/50 focus:outline-none"
                  />
                </label>
                {tooLarge && (
                  <p className="text-xs text-amber-300">
                    {origin.name} supports at most {origin.max_context?.toLocaleString()} tokens.
                  </p>
                )}
                {existing && (
                  <p className="text-xs text-white/50">
                    <span className="font-mono text-white/75">{existing.name}</span> already exists, so nothing new
                    is created: it is tested as it is.
                  </p>
                )}
              </div>
            )}

            {step === 'result' && (
              <div className="space-y-4">
                {build.isPending && <Progress text={`Creating ${finalName}...`} />}
                {test.isPending && (
                  <Progress
                    text={`Loading ${finalName} once to see whether it fits.`}
                    note="This can take a minute or more for a large model."
                  />
                )}
                {failure && (
                  <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    {failure}
                  </div>
                )}
                {result?.load?.loads && (
                  <div className="rounded-xl border border-emerald-400/25 bg-emerald-400/10 px-4 py-4">
                    <p className="flex items-center gap-2 text-sm font-semibold text-emerald-300">
                      <Check size={15} /> <span className="font-mono">{result.name}</span> loads on this machine
                    </p>
                    <p className="mt-1.5 text-xs leading-relaxed text-white/55">
                      {[
                        result.context ? `${result.context.toLocaleString()} tokens of context` : '',
                        memoryText(result.load),
                        `loaded in ${result.load.seconds} s`,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                    <p className="mt-1.5 text-xs text-white/40">
                      Use it under this name wherever you pick a model. It shares the files of{' '}
                      <span className="font-mono">{result.built_from ?? root}</span>.
                    </p>
                  </div>
                )}
                {result?.load && !result.load.loads && (
                  <div className="rounded-xl border border-amber-400/25 bg-amber-400/10 px-4 py-4">
                    <p className="flex items-center gap-2 text-sm font-semibold text-amber-300">
                      <AlertTriangle size={15} /> <span className="font-mono">{result.name}</span> does not load on
                      this machine
                    </p>
                    <p className="mt-1.5 text-xs leading-relaxed text-white/55">
                      {result.load.reason}
                      {result.load.try_context
                        ? ` A smaller context window needs less memory. Closing other applications also frees memory.`
                        : ' Closing other applications frees memory.'}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* footer */}
          <div className="flex items-center justify-between gap-3 border-t border-white/5 px-6 py-4">
            <div>
              {step === 'context' && !initialSource && <Ghost onClick={() => setStep('model')}>Back</Ghost>}
              {step === 'result' && !busy && <Ghost onClick={() => setStep('context')}>Choose another size</Ghost>}
            </div>
            <div className="flex items-center gap-2">
              {step === 'model' && (
                <Primary disabled={!origin} onClick={() => setStep('context')}>
                  Next
                </Primary>
              )}
              {step === 'context' && (
                <Primary disabled={!ready} onClick={() => context && run(context, finalName, !!existing)}>
                  {existing ? 'Test it' : 'Create and test'}
                </Primary>
              )}
              {step === 'result' && !busy && result?.load && !result.load.loads && result.load.try_context && (
                <Primary onClick={() => trySmaller(result.load!.try_context!)}>
                  Try {sizeLabel(result.load.try_context)} instead
                </Primary>
              )}
              {step === 'result' && !busy && <Ghost onClick={onClose}>Done</Ghost>}
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  )
}

function Progress({ text, note }: { text: string; note?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center">
      <Loader2 size={22} className="animate-spin" style={{ color: CYAN }} />
      <p className="text-sm text-white/70">{text}</p>
      {note && <p className="text-xs text-white/35">{note}</p>}
    </div>
  )
}

function Primary({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
      style={{
        background: `linear-gradient(135deg, ${CYAN}26, rgba(139,92,246,0.2))`,
        border: `1px solid ${CYAN}40`,
        color: CYAN,
      }}
      whileHover={disabled ? undefined : { scale: 1.02 }}
      whileTap={disabled ? undefined : { scale: 0.98 }}
    >
      {children}
    </motion.button>
  )
}

function Ghost({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white/65 transition-colors hover:bg-white/[0.07] hover:text-white/85"
    >
      {children}
    </button>
  )
}
