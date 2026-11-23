/**
 * "Get models": find a model that is not installed yet and download it into
 * the local Ollama runtime.
 *
 *   Ollama library   search ollama.com
 *   Hugging Face     search GGUF repositories; Ollama installs them directly
 *   For this PC      models that fit this machine (FitLab data; off until asked)
 *   Custom           any reference Ollama can pull, e.g. a private registry
 *
 * Downloads keep running when the drawer is closed; the page owns their list.
 */
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Cpu,
  Download,
  Heart,
  Link2,
  Loader2,
  Search,
  Sparkles,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  useCreateVariant,
  useLibraryBuilds,
  useLibrarySearch,
  useRecommendations,
  useSetRecommendations,
} from '../../lib/localHooks'
import type { LibraryResult, LibrarySource, RecommendedModel } from '../../lib/localApi'
import { DownloadCard } from './DownloadCard'
import { formatBytes, normalizeRef } from './modelRefs'

const CYAN = '#00e5ff'

type Tab = 'ollama' | 'huggingface' | 'pc' | 'custom'

const TABS: { id: Tab; label: string }[] = [
  { id: 'ollama', label: 'Ollama library' },
  { id: 'huggingface', label: 'Hugging Face' },
  { id: 'pc', label: 'For this PC' },
  { id: 'custom', label: 'Custom' },
]

function compact(n: number | null | undefined): string {
  if (n == null) return ''
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}K`
  return String(n)
}

type DownloadActions = {
  installed: Set<string>
  /** The installed ids as the runtime spells them, for pickers. */
  installedIds: string[]
  tracked: Set<string>
  onStart: (ref: string) => void
  onInstalled: () => void
}

export function GetModelsDrawer({
  open,
  onClose,
  installed,
  downloads,
  onStart,
  onDismiss,
  onInstalled,
}: {
  open: boolean
  onClose: () => void
  /** Model ids the runtime already has. */
  installed: string[]
  /** References being downloaded, or finished and not dismissed yet. */
  downloads: string[]
  onStart: (ref: string) => void
  onDismiss: (ref: string) => void
  onInstalled: () => void
}) {
  const [tab, setTab] = useState<Tab>('ollama')

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const actions: DownloadActions = useMemo(
    () => ({
      installed: new Set(installed.map(normalizeRef)),
      installedIds: installed,
      tracked: new Set(downloads.map(normalizeRef)),
      onStart,
      onInstalled,
    }),
    [installed, downloads, onStart, onInstalled],
  )

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[140]">
          <motion.div
            className="absolute inset-0 bg-black/55 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-label="Get models"
            className="absolute inset-y-0 right-0 flex w-full flex-col sm:w-[620px]"
            style={{
              background: 'linear-gradient(160deg, rgba(12,17,48,0.98), rgba(6,10,26,0.98))',
              borderLeft: '1px solid rgba(100,160,255,0.14)',
              boxShadow: '-24px 0 80px rgba(0,0,0,0.55)',
            }}
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 260, damping: 32 }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 pb-4 pt-5">
              <div className="flex items-center gap-3">
                <div
                  className="flex h-9 w-9 items-center justify-center rounded-xl"
                  style={{
                    background: 'linear-gradient(135deg, rgba(0,229,255,0.18), rgba(139,92,246,0.14))',
                    border: '1px solid rgba(0,229,255,0.25)',
                  }}
                >
                  <Download size={16} style={{ color: CYAN }} />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-white/90">Get models</h2>
                  <p className="text-xs text-white/35">Search, download, and use them on this machine</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="rounded-xl border border-white/10 bg-white/5 p-2 text-white/40 transition-colors hover:border-white/20 hover:text-white/75"
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 px-6" role="tablist">
              {TABS.map((item) => (
                <button
                  key={item.id}
                  role="tab"
                  aria-selected={tab === item.id}
                  onClick={() => setTab(item.id)}
                  className="relative rounded-t-lg px-3 py-2 text-sm transition-colors"
                  style={{ color: tab === item.id ? CYAN : 'rgba(255,255,255,0.45)' }}
                >
                  {item.label}
                  {tab === item.id && (
                    <motion.span
                      layoutId="get-models-tab"
                      className="absolute inset-x-2 -bottom-px h-0.5 rounded-full"
                      style={{ background: CYAN, boxShadow: `0 0 10px ${CYAN}` }}
                    />
                  )}
                </button>
              ))}
            </div>
            <div className="border-b border-white/[0.07]" />

            {/* Body */}
            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
              {tab === 'ollama' && <LibrarySearch key="ollama" source="ollama" actions={actions} />}
              {tab === 'huggingface' && <LibrarySearch key="huggingface" source="huggingface" actions={actions} />}
              {tab === 'pc' && <ForThisPc actions={actions} />}
              {tab === 'custom' && <CustomReference actions={actions} />}
            </div>

            {/* Downloads */}
            {downloads.length > 0 && (
              <div className="max-h-[42%] overflow-y-auto border-t border-white/[0.07] bg-black/20 px-6 py-4">
                <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-white/35">Downloads</p>
                <div className="space-y-2.5">
                  <AnimatePresence initial={false}>
                    {downloads.map((ref) => (
                      <DownloadCard
                        key={ref}
                        modelRef={ref}
                        onInstalled={onInstalled}
                        onDismiss={() => onDismiss(ref)}
                      />
                    ))}
                  </AnimatePresence>
                </div>
              </div>
            )}
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  )
}

// ── Search (Ollama library or Hugging Face) ─────────────────────────────

function LibrarySearch({ source, actions }: { source: LibrarySource; actions: DownloadActions }) {
  const [text, setText] = useState('')
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    input.current?.focus()
  }, [])
  useEffect(() => {
    const timer = setTimeout(() => setQuery(text.trim()), 350)
    return () => clearTimeout(timer)
  }, [text])

  const { data, isFetching, error } = useLibrarySearch(query, source)
  const results = data?.results ?? []
  const site = source === 'ollama' ? 'ollama.com' : 'Hugging Face'

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/30" />
        <input
          ref={input}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={source === 'ollama' ? 'Search the Ollama library…' : 'Search GGUF models on Hugging Face…'}
          className="w-full rounded-xl border border-white/10 bg-white/5 py-2.5 pl-10 pr-10 text-sm text-white/85 placeholder:text-white/25 focus:border-glow-cyan/50 focus:outline-none"
        />
        {isFetching && (
          <Loader2 size={15} className="absolute right-3.5 top-1/2 -translate-y-1/2 animate-spin text-white/35" />
        )}
      </div>

      {error && (
        <Notice tone="warn">
          {site} could not be searched right now. You can still download a model by its exact name under Custom.
        </Notice>
      )}

      {!error && !isFetching && data && results.length === 0 && (
        <Notice>
          Nothing found{query ? ` for “${query}”` : ''}. If you know the exact name, download it under Custom.
        </Notice>
      )}

      {!query && results.length > 0 && (
        <p className="text-[11px] uppercase tracking-wider text-white/30">Popular on {site}</p>
      )}

      <div className="space-y-2">
        {results.map((result) => (
          <ResultRow
            key={result.name}
            result={result}
            source={source}
            open={expanded === result.name}
            onToggle={() => setExpanded(expanded === result.name ? null : result.name)}
            actions={actions}
          />
        ))}
      </div>
    </div>
  )
}

function ResultRow({
  result,
  source,
  open,
  onToggle,
  actions,
}: {
  result: LibraryResult
  source: LibrarySource
  open: boolean
  onToggle: () => void
  actions: DownloadActions
}) {
  return (
    <div className="glass-card-sm overflow-hidden">
      <button onClick={onToggle} className="flex w-full items-start gap-3 px-4 py-3 text-left" aria-expanded={open}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate font-mono text-sm font-medium text-white/85">{result.name}</span>
            {result.capabilities.map((capability) => (
              <span
                key={capability}
                className="rounded-full border border-glow-violet/30 bg-glow-violet/10 px-1.5 py-px text-[10px] text-glow-violet"
              >
                {capability}
              </span>
            ))}
          </div>
          {result.description && <p className="mt-1 line-clamp-2 text-xs text-white/40">{result.description}</p>}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-white/30">
            {result.downloads != null && (
              <span className="flex items-center gap-1">
                <Download size={11} /> {compact(result.downloads)}
              </span>
            )}
            {result.likes != null && (
              <span className="flex items-center gap-1">
                <Heart size={11} /> {compact(result.likes)}
              </span>
            )}
            {result.sizes.length > 0 && <span>{result.sizes.join(' · ')}</span>}
          </div>
        </div>
        <motion.span animate={{ rotate: open ? 180 : 0 }} className="mt-1 shrink-0 text-white/35">
          <ChevronDown size={16} />
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-white/[0.06]"
          >
            <Builds result={result} source={source} actions={actions} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** The versions of one model: its parameter sizes on Ollama, its quantizations on Hugging Face. */
function Builds({ result, source, actions }: { result: LibraryResult; source: LibrarySource; actions: DownloadActions }) {
  const { data, isLoading, error } = useLibraryBuilds(result.name, source, source === 'ollama' ? result.sizes : [])
  const builds = (data?.tags ?? []).filter((build) => build.available)

  if (isLoading) {
    return (
      <p className="flex items-center gap-2 px-4 py-3 text-xs text-white/40">
        <Loader2 size={13} className="animate-spin" /> Looking up the available versions…
      </p>
    )
  }
  if (error || builds.length === 0) {
    return (
      <p className="px-4 py-3 text-xs text-white/40">
        {source === 'huggingface'
          ? 'This repository has no single-file GGUF build that Ollama can install.'
          : 'No version of this model can be downloaded to this machine (it may be cloud-only).'}
      </p>
    )
  }
  return (
    <ul className="divide-y divide-white/[0.05]">
      {builds.map((build, index) => (
        <li key={build.ref} className="flex items-center gap-3 px-4 py-2.5">
          <span className="w-24 shrink-0 font-mono text-xs text-white/75">{build.tag}</span>
          <span className="flex-1 text-xs tabular-nums text-white/40">
            {formatBytes(build.size_bytes)}
            {source === 'huggingface' && index === 0 && build.tag === 'Q4_K_M' && (
              <span className="ml-2 text-white/30">the usual choice</span>
            )}
          </span>
          <PullButton modelRef={build.ref} actions={actions} />
        </li>
      ))}
    </ul>
  )
}

// ── For this PC (FitLab, opt-in) ─────────────────────────────────────────

function ForThisPc({ actions }: { actions: DownloadActions }) {
  const { data, isLoading } = useRecommendations()
  const toggle = useSetRecommendations()

  if (isLoading) {
    return (
      <p className="flex items-center gap-2 py-6 text-sm text-white/40">
        <Loader2 size={14} className="animate-spin" /> Checking what fits this machine…
      </p>
    )
  }

  if (!data?.enabled) {
    return (
      <div className="glass-card-sm px-5 py-6 text-center">
        <Sparkles size={22} className="mx-auto mb-3 text-glow-violet" />
        <h3 className="text-sm font-semibold text-white/85">Recommend models for this PC</h3>
        <p className="mx-auto mt-2 max-w-sm text-xs leading-relaxed text-white/45">
          OllaBridge reads this machine's GPU and memory and lists the models that fit, most liked first. The list
          comes from FitLab's public registry. Your hardware details never leave this machine. This is off until you
          turn it on.
        </p>
        <button
          onClick={() => toggle.mutate(true)}
          disabled={toggle.isPending}
          className="mt-4 rounded-xl px-4 py-2 text-sm font-medium"
          style={{
            background: 'linear-gradient(135deg, rgba(0,229,255,0.16), rgba(139,92,246,0.16))',
            border: '1px solid rgba(0,229,255,0.28)',
            color: CYAN,
          }}
        >
          {toggle.isPending ? 'Turning on…' : 'Turn on recommendations'}
        </button>
      </div>
    )
  }

  const { hardware, models = [], registry, assumptions, error } = data
  return (
    <div className="space-y-3">
      {hardware && (
        <div className="glass-card-sm flex items-center gap-3 px-4 py-3">
          <Cpu size={16} className="shrink-0 text-glow-cyan" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-white/80">{hardware.name}</p>
            <p className="text-xs text-white/40">
              {hardware.budget_gb} GB {hardware.budget}
              {hardware.kind !== 'cpu' && hardware.ram_gb > 0 && ` · ${hardware.ram_gb} GB RAM`}
            </p>
          </div>
          <button
            onClick={() => toggle.mutate(false)}
            className="shrink-0 text-xs text-white/30 underline-offset-2 hover:text-white/60 hover:underline"
          >
            Turn off
          </button>
        </div>
      )}

      {error && <Notice tone="warn">{error}</Notice>}
      {!error && models.length === 0 && (
        <Notice>No model in the FitLab registry fits this machine's memory.</Notice>
      )}

      <div className="space-y-2">
        {models.map((model) => (
          <RecommendedRow key={model.ollama_tag} model={model} actions={actions} />
        ))}
      </div>

      {registry && (
        <p className="pt-1 text-[11px] text-white/25">
          FitLab registry of {registry.generated_at ?? 'unknown date'}
          {assumptions && ` · estimated for ${assumptions.quantization} at ${assumptions.context / 1024}K context`}
        </p>
      )}
    </div>
  )
}

function RecommendedRow({ model, actions }: { model: RecommendedModel; actions: DownloadActions }) {
  const tight = model.verdict === 'tight'
  return (
    <div className="glass-card-sm flex items-center gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate font-mono text-sm font-medium text-white/85">{model.ollama_tag}</span>
          <span
            className="rounded-full px-1.5 py-px text-[10px] font-medium"
            style={
              tight
                ? { background: 'rgba(245,158,11,0.12)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.3)' }
                : { background: 'rgba(52,211,153,0.12)', color: '#34d399', border: '1px solid rgba(52,211,153,0.3)' }
            }
            title={tight ? 'Fits, with little memory to spare' : 'Fits comfortably'}
          >
            {tight ? 'tight fit' : 'fits'}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-white/35">
          <span>needs about {model.est_gb} GB</span>
          <span className="flex items-center gap-1">
            <Heart size={11} /> {compact(model.likes)}
          </span>
          {model.capabilities.length > 0 && <span>{model.capabilities.join(' · ')}</span>}
        </div>
      </div>
      <PullButton modelRef={model.ollama_tag} actions={actions} />
    </div>
  )
}

// ── Custom reference ─────────────────────────────────────────────────────

function CustomReference({ actions }: { actions: DownloadActions }) {
  const [ref, setRef] = useState('')
  const clean = ref.trim()
  const valid = clean.length > 0 && !/\s/.test(clean)

  return (
    <div className="space-y-4">
      <p className="text-xs leading-relaxed text-white/45">
        Download any model Ollama can pull, by its exact reference. Use this for a model on a private registry, or
        when you already know the name.
      </p>
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (valid) actions.onStart(clean)
        }}
      >
        <div className="relative flex-1">
          <Link2 size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/30" />
          <input
            value={ref}
            onChange={(event) => setRef(event.target.value)}
            placeholder="model:tag"
            className="w-full rounded-xl border border-white/10 bg-white/5 py-2.5 pl-10 pr-3 font-mono text-sm text-white/85 placeholder:text-white/25 focus:border-glow-cyan/50 focus:outline-none"
          />
        </div>
        {valid ? <PullButton modelRef={clean} actions={actions} /> : <PullButton modelRef="" actions={actions} disabled />}
      </form>
      <div className="space-y-1.5 text-xs text-white/35">
        <p className="text-[11px] uppercase tracking-wider text-white/25">Examples</p>
        {['qwen2.5:7b', 'hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M', 'registry.example.com/team/model:tag'].map(
          (example) => (
            <button
              key={example}
              type="button"
              onClick={() => setRef(example)}
              className="block font-mono text-white/45 hover:text-white/80"
            >
              {example}
            </button>
          ),
        )}
      </div>

      <ContextVariant actions={actions} />
    </div>
  )
}

const CONTEXT_SIZES = [4096, 8192, 16384, 32768]

/**
 * An installed model under a new name with a fixed context window: what a
 * two-line Modelfile (FROM model, PARAMETER num_ctx) does. Nothing is downloaded.
 */
function ContextVariant({ actions }: { actions: DownloadActions }) {
  const create = useCreateVariant()
  const [source, setSource] = useState('')
  const [context, setContext] = useState(8192)
  const [name, setName] = useState('')
  const [nameEdited, setNameEdited] = useState(false)

  // Suggest "<model>-8k" until the user types a name of their own.
  const suggested = source.trim() ? `${source.trim().split(':')[0].split('/').pop()}-${context / 1024}k` : ''
  const finalName = nameEdited ? name.trim() : suggested
  const ready = source.trim().length > 0 && /^[A-Za-z0-9][A-Za-z0-9._-]*(:[A-Za-z0-9._-]+)?$/.test(finalName)

  return (
    <div className="glass-card-sm space-y-3 px-4 py-4">
      <div>
        <h3 className="text-sm font-semibold text-white/80">Copy with a set context window</h3>
        <p className="mt-1 text-xs leading-relaxed text-white/40">
          Gives an installed model a second name that always runs with the context size you pick. It shares the
          original's files, so it takes no extra disk space.
        </p>
      </div>
      <form
        className="space-y-2.5"
        onSubmit={(event) => {
          event.preventDefault()
          if (!ready) return
          create.mutate(
            { source: source.trim(), name: finalName, num_ctx: context },
            { onSuccess: actions.onInstalled },
          )
        }}
      >
        <label className="block text-[11px] uppercase tracking-wider text-white/30">
          Installed model
          <input
            list="installed-models"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            placeholder="pick or type a model"
            className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 font-mono text-sm normal-case tracking-normal text-white/85 placeholder:text-white/25 focus:border-glow-cyan/50 focus:outline-none"
          />
          <datalist id="installed-models">
            {actions.installedIds.map((id) => (
              <option key={id} value={id} />
            ))}
          </datalist>
        </label>
        <div className="flex gap-2.5">
          <label className="block w-36 shrink-0 text-[11px] uppercase tracking-wider text-white/30">
            Context
            <select
              value={context}
              onChange={(event) => setContext(Number(event.target.value))}
              className="mt-1 w-full rounded-lg border border-white/10 bg-navy-800 px-3 py-2 text-sm normal-case tracking-normal text-white/85 focus:border-glow-cyan/50 focus:outline-none"
            >
              {CONTEXT_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size / 1024}K tokens
                </option>
              ))}
            </select>
          </label>
          <label className="block min-w-0 flex-1 text-[11px] uppercase tracking-wider text-white/30">
            New name
            <input
              value={finalName}
              onChange={(event) => {
                setNameEdited(true)
                setName(event.target.value)
              }}
              placeholder="model-8k"
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 font-mono text-sm normal-case tracking-normal text-white/85 placeholder:text-white/25 focus:border-glow-cyan/50 focus:outline-none"
            />
          </label>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={!ready || create.isPending}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40"
            style={{ background: `${CYAN}14`, border: `1px solid ${CYAN}38`, color: CYAN }}
          >
            {create.isPending ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
            Create
          </button>
          {create.isSuccess && (
            <span className="flex items-center gap-1 text-xs text-emerald-300">
              <Check size={12} /> {create.data.name} is ready to use
            </span>
          )}
          {create.isError && <span className="text-xs text-red-300">{(create.error as Error).message}</span>}
        </div>
      </form>
    </div>
  )
}

// ── Shared ──────────────────────────────────────────────────────────────

function PullButton({
  modelRef,
  actions,
  disabled = false,
}: {
  modelRef: string
  actions: DownloadActions
  disabled?: boolean
}) {
  const key = normalizeRef(modelRef)
  if (key && actions.installed.has(key)) {
    return (
      <span className="flex shrink-0 items-center gap-1 rounded-lg border border-emerald-400/25 bg-emerald-400/10 px-2.5 py-1.5 text-xs text-emerald-300">
        <Check size={12} /> Installed
      </span>
    )
  }
  if (key && actions.tracked.has(key)) {
    return (
      <span className="flex shrink-0 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-white/45">
        <Loader2 size={12} className="animate-spin" /> In downloads
      </span>
    )
  }
  return (
    <motion.button
      type={disabled ? 'button' : 'submit'}
      disabled={disabled}
      onClick={(event) => {
        event.preventDefault()
        if (!disabled) actions.onStart(modelRef)
      }}
      whileTap={disabled ? undefined : { scale: 0.95 }}
      className="flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40"
      style={{ background: `${CYAN}14`, border: `1px solid ${CYAN}38`, color: CYAN }}
    >
      <Download size={12} /> Download
    </motion.button>
  )
}

function Notice({ children, tone = 'info' }: { children: React.ReactNode; tone?: 'info' | 'warn' }) {
  return (
    <div
      className="flex items-start gap-2.5 rounded-xl px-4 py-3 text-xs leading-relaxed"
      style={
        tone === 'warn'
          ? { background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.22)', color: 'rgba(253,230,138,0.85)' }
          : { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.5)' }
      }
    >
      {tone === 'warn' && <AlertTriangle size={14} className="mt-px shrink-0" />}
      <span>{children}</span>
    </div>
  )
}
