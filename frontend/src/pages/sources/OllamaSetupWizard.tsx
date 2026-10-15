import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Copy,
  Download,
  ExternalLink,
  Link2,
  Loader2,
  Package,
  Play,
  RefreshCw,
  Server,
  Terminal,
  X,
} from 'lucide-react'
import { api } from '../../lib/api'
import type { OllamaPullProgress, OllamaSetupJob, OllamaSetupStatus } from '../../lib/api'
import type { Page } from '../../App'

/**
 * "Set up Ollama" — the few-clicks path from "nothing local" to "a model
 * answering", for someone who installed OllaBridge and found no runtime.
 *
 * The backend (`/admin/ollama-setup/*`) inspects the machine and names the
 * one step that matters; the wizard opens on that step and chains the rest:
 * install → start → first model, each a single click, each verified by a
 * real probe before moving on. When this process cannot do a step itself
 * (container, no passwordless sudo, no package manager) the screen says why
 * and hands over the exact official command instead of pretending.
 *
 * Additive: it only writes the Ollama URL / enabled flag through the same
 * settings endpoint the Runtimes form uses, and never removes anything.
 */

type Step = 'check' | 'connect' | 'install' | 'start' | 'model' | 'done'

const RAIL: Array<{ label: string; hint: string }> = [
  { label: 'Check', hint: 'Look for Ollama' },
  { label: 'Install', hint: 'Official installer' },
  { label: 'Start', hint: 'Bring it up' },
  { label: 'First model', hint: 'Pull one to chat' },
]

function railIndex(step: Step): number {
  switch (step) {
    case 'check':
      return 0
    case 'install':
      return 1
    case 'connect':
    case 'start':
      return 2
    case 'model':
      return 3
    case 'done':
      return 4
  }
}

const ACTIVE_PULL = new Set(['queued', 'running'])
const CYAN = '#00e5ff'

function errorText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback
}

function fmtBytes(n: number | null | undefined): string {
  if (!n || n <= 0) return ''
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`
  if (n >= 1e6) return `${Math.round(n / 1e6)} MB`
  return `${Math.round(n / 1e3)} kB`
}

export function OllamaSetupWizard({
  onClose,
  onNavigate,
}: {
  onClose: () => void
  onNavigate?: (page: Page) => void
}) {
  const queryClient = useQueryClient()
  const titleId = useId()
  const [status, setStatus] = useState<OllamaSetupStatus | null>(null)
  const [checking, setChecking] = useState(true)
  const [checkError, setCheckError] = useState<string | null>(null)
  const [step, setStep] = useState<Step>('check')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [job, setJob] = useState<OllamaSetupJob | null>(null)
  const [selectedModel, setSelectedModel] = useState('')
  const [pull, setPull] = useState<OllamaPullProgress | null>(null)
  const [copied, setCopied] = useState(false)

  // Every page that shows Ollama state re-reads after the wizard changes it.
  const notifyChanged = useCallback(() => {
    for (const key of [
      'settings',
      'models',
      'modelAccess',
      'runtimes',
      'health',
      'cloudModelManifest',
      'cloudStatus',
      'sourceHealth',
    ]) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  }, [queryClient])

  const ensureEnabled = useCallback(
    async (s: OllamaSetupStatus, url?: string) => {
      const wantUrl = url ?? s.settings.ollama_base_url
      if (s.settings.local_runtime_enabled && wantUrl === s.settings.ollama_base_url) return
      await api.updateSettings({ local_runtime_enabled: true, ollama_base_url: wantUrl })
      notifyChanged()
    },
    [notifyChanged],
  )

  /** Inspect the machine; with `decide`, jump to the step that matters. */
  const check = useCallback(
    async (decide: boolean): Promise<OllamaSetupStatus | null> => {
      setChecking(true)
      setCheckError(null)
      setActionError(null)
      try {
        const s = await api.ollamaSetupStatus()
        setStatus(s)
        if (decide) {
          switch (s.recommended) {
            case 'ready':
              await ensureEnabled(s)
              setStep('done')
              break
            case 'pull':
              await ensureEnabled(s)
              setStep('model')
              break
            case 'connect':
              setStep('connect')
              break
            case 'start':
              setStep('start')
              break
            default:
              setStep('install')
          }
        }
        return s
      } catch (e) {
        setCheckError(errorText(e, 'Could not inspect this machine'))
        return null
      } finally {
        setChecking(false)
      }
    },
    [ensureEnabled],
  )

  useEffect(() => {
    void check(true)
  }, [check])

  useEffect(() => {
    if (status && !selectedModel) setSelectedModel(status.suggested_models[0]?.id ?? '')
  }, [status, selectedModel])

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

  // ── actions ──────────────────────────────────────────────────────────

  async function startOllama() {
    setBusy(true)
    setActionError(null)
    setStep('start')
    try {
      const r = await api.ollamaSetupStart()
      if (r.reachable) {
        notifyChanged()
        await check(true)
      } else {
        setActionError(r.message ?? `Ollama did not answer at ${r.url}`)
      }
    } catch (e) {
      setActionError(errorText(e, 'Could not start Ollama'))
    } finally {
      setBusy(false)
    }
  }

  async function runInstall() {
    setBusy(true)
    setActionError(null)
    try {
      setJob(await api.ollamaSetupInstall())
    } catch (e) {
      setActionError(errorText(e, 'Could not start the installer'))
      setBusy(false)
    }
  }

  const jobId = job?.job_id
  const jobRunning = job?.status === 'running'
  useEffect(() => {
    if (!jobId || !jobRunning) return
    const timer = setInterval(async () => {
      try {
        const j = await api.ollamaSetupJob(jobId)
        setJob(j)
        if (j.status === 'succeeded') {
          clearInterval(timer)
          void startOllama() // installed → bring it up without another click
        } else if (j.status === 'failed') {
          clearInterval(timer)
          setBusy(false)
          setActionError(j.error ?? `The installer exited with code ${j.exit_code ?? '?'}`)
        }
      } catch (e) {
        clearInterval(timer)
        setBusy(false)
        setActionError(errorText(e, 'Lost track of the installer'))
      }
    }, 1000)
    return () => clearInterval(timer)
    // startOllama is a plain closure over stable setters and `check`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobRunning])

  async function connectTo(url: string) {
    setBusy(true)
    setActionError(null)
    try {
      await api.updateSettings({ ollama_base_url: url, local_runtime_enabled: true })
      notifyChanged()
      await check(true)
    } catch (e) {
      setActionError(errorText(e, 'Could not save the address'))
    } finally {
      setBusy(false)
    }
  }

  async function startPull() {
    if (!selectedModel) return
    setBusy(true)
    setActionError(null)
    try {
      setPull(await api.ollamaSetupPull(selectedModel))
    } catch (e) {
      setActionError(errorText(e, 'Could not start the download'))
      setBusy(false)
    }
  }

  const pullModel = pull?.model
  const pullActive = !!pull && ACTIVE_PULL.has(pull.status)
  useEffect(() => {
    if (!pullModel || !pullActive) return
    const timer = setInterval(async () => {
      try {
        const p = await api.ollamaSetupPullStatus(pullModel)
        setPull(p)
        if (p.status === 'completed') {
          clearInterval(timer)
          setBusy(false)
          notifyChanged()
          setStep('done')
          void check(false)
        } else if (!ACTIVE_PULL.has(p.status)) {
          clearInterval(timer)
          setBusy(false)
          setActionError(p.error ?? 'The download failed')
        }
      } catch (e) {
        clearInterval(timer)
        setBusy(false)
        setActionError(errorText(e, 'Lost track of the download'))
      }
    }, 1000)
    return () => clearInterval(timer)
  }, [pullModel, pullActive, check, notifyChanged])

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable (http origin); the command is still visible
    }
  }

  // ── render ───────────────────────────────────────────────────────────

  const idx = railIndex(step)
  const wslHost = status?.candidates.find((c) => c.label.startsWith('Windows host'))

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
          className="relative w-full max-w-2xl rounded-2xl border border-white/10 bg-navy-800/95 backdrop-blur-xl shadow-2xl overflow-hidden"
        >
          {/* header */}
          <div className="flex items-start justify-between gap-3 px-6 pt-6 pb-4 border-b border-white/5">
            <div className="flex items-center gap-3">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center"
                style={{
                  background: `linear-gradient(135deg, ${CYAN}22, ${CYAN}08)`,
                  border: `1px solid ${CYAN}30`,
                }}
              >
                <Server size={18} style={{ color: CYAN }} />
              </div>
              <div>
                <h2 id={titleId} className="text-white font-bold text-base">
                  Set up Ollama
                </h2>
                <p className="text-white/40 text-xs">
                  Local models on this machine, in a few clicks
                  {status ? ` · ${status.platform_label}` : ''}
                </p>
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

          {/* step rail */}
          <ol className="flex items-center gap-2 px-6 py-4 border-b border-white/5">
            {RAIL.map((r, i) => {
              const done = i < idx
              const active = i === idx
              return (
                <li key={r.label} className="flex items-center gap-2 flex-1 min-w-0">
                  <span
                    className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0 transition-colors"
                    style={{
                      background: done ? `${CYAN}26` : active ? `${CYAN}14` : 'rgba(255,255,255,0.04)',
                      border: `1px solid ${done || active ? `${CYAN}60` : 'rgba(255,255,255,0.1)'}`,
                      color: done || active ? CYAN : 'rgba(255,255,255,0.35)',
                    }}
                  >
                    {done ? <Check size={12} /> : i + 1}
                  </span>
                  <span className="min-w-0">
                    <span
                      className={`block text-xs font-medium truncate ${
                        active ? 'text-white/90' : done ? 'text-white/60' : 'text-white/35'
                      }`}
                    >
                      {r.label}
                    </span>
                    <span className="block text-[10px] text-white/25 truncate">{r.hint}</span>
                  </span>
                  {i < RAIL.length - 1 && (
                    <span
                      className="h-px flex-1 mx-1"
                      style={{ background: done ? `${CYAN}50` : 'rgba(255,255,255,0.08)' }}
                    />
                  )}
                </li>
              )
            })}
          </ol>

          {/* diagnostics strip */}
          {status && (
            <div className="flex flex-wrap gap-2 px-6 pt-4">
              <Fact
                ok={status.binary.found}
                label={
                  status.binary.found
                    ? `Ollama ${status.binary.version ?? ''} installed`.trim()
                    : 'Ollama not installed'
                }
                title={status.binary.path ?? undefined}
              />
              <Fact
                ok={status.service.reachable}
                label={
                  status.service.reachable
                    ? `Running at ${status.service.url} · ${status.service.models} model${
                        status.service.models === 1 ? '' : 's'
                      }`
                    : `Not answering at ${status.service.url}`
                }
              />
              {status.in_docker && <Fact ok={null} label="Inside a container" />}
              {status.in_wsl && <Fact ok={null} label="WSL" />}
            </div>
          )}

          {/* body */}
          <div className="px-6 py-5 min-h-[220px]">
            {step === 'check' && (
              <Panel>
                {checking ? (
                  <Busy text="Looking for Ollama on this machine…" />
                ) : checkError ? (
                  <ErrorBox text={checkError} onRetry={() => check(true)} />
                ) : (
                  <Busy text="Deciding where to start…" />
                )}
              </Panel>
            )}

            {step === 'connect' && status && (
              <Panel>
                <Heading
                  icon={Link2}
                  title="Ollama is already running nearby"
                  text={`The gateway is pointed at ${status.settings.ollama_base_url}, which does not answer. One click points it at an address that does.`}
                />
                <div className="space-y-2">
                  {status.candidates
                    .filter((c) => c.reachable)
                    .map((c) => (
                      <div
                        key={c.url}
                        className="flex items-center gap-3 px-3.5 py-3 rounded-xl bg-navy-900/50 border border-white/[0.06]"
                      >
                        <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399] shrink-0" />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-mono text-white/85 truncate">{c.url}</div>
                          <div className="text-[11px] text-white/40">
                            {c.label} · {c.models} model{c.models === 1 ? '' : 's'}
                          </div>
                        </div>
                        <Primary onClick={() => connectTo(c.url)} disabled={busy} icon={Link2}>
                          Use this address
                        </Primary>
                      </div>
                    ))}
                </div>
                {actionError && <ErrorBox text={actionError} />}
                <Ghost onClick={() => setStep('install')}>Install here instead</Ghost>
              </Panel>
            )}

            {step === 'install' && status && (
              <Panel>
                <Heading
                  icon={Download}
                  title={`Install Ollama on ${status.platform_label}`}
                  text={
                    status.install.can_run_here
                      ? 'OllaBridge runs the official installer for you. Nothing else is downloaded or changed, and it starts Ollama when done.'
                      : status.install.reason
                  }
                  tone={status.install.can_run_here ? 'normal' : 'warn'}
                />

                <CommandBox
                  command={status.install.display_command}
                  copied={copied}
                  onCopy={() => copy(status.install.display_command)}
                  caption={status.install.can_run_here ? 'What will run' : 'Run this in a terminal'}
                />

                {job && (
                  <LogConsole
                    lines={job.lines}
                    status={job.status}
                    exitCode={job.exit_code}
                  />
                )}

                {actionError && <ErrorBox text={actionError} />}

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  {status.install.can_run_here && (!job || job.status === 'failed') && (
                    <Primary onClick={runInstall} disabled={busy} icon={Download}>
                      {job ? 'Retry install' : 'Install Ollama'}
                    </Primary>
                  )}
                  {job?.status === 'running' && <Busy text="Installing… this can take a few minutes" inline />}
                  {(!status.install.can_run_here || job?.status === 'failed') && (
                    <a
                      href={status.install.download_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors"
                      style={{
                        background: `linear-gradient(135deg, ${CYAN}26, rgba(139,92,246,0.2))`,
                        border: `1px solid ${CYAN}40`,
                        color: CYAN,
                      }}
                    >
                      <ExternalLink size={14} /> Download for {status.platform_label}
                    </a>
                  )}
                  <Ghost onClick={() => check(true)} disabled={busy || checking} icon={RefreshCw}>
                    I installed it, check again
                  </Ghost>
                </div>

                {status.in_wsl && (
                  <Hint
                    title="Running Ollama on Windows instead?"
                    text={`On Windows set the environment variable OLLAMA_HOST to 0.0.0.0, restart Ollama, then use ${
                      wslHost?.url ?? 'http://<windows-host-ip>:11434'
                    } here.`}
                    action={
                      wslHost ? (
                        <Ghost onClick={() => connectTo(wslHost.url)} disabled={busy} icon={Link2}>
                          Use {wslHost.url}
                        </Ghost>
                      ) : null
                    }
                  />
                )}
              </Panel>
            )}

            {step === 'start' && status && (
              <Panel>
                <Heading
                  icon={Play}
                  title="Ollama is installed but not running"
                  text={`Nothing answers at ${status.settings.ollama_base_url}. Starting it here launches "ollama serve" in the background and waits for it to come up.`}
                />
                {actionError && <ErrorBox text={actionError} />}
                <div className="flex flex-wrap items-center gap-2">
                  <Primary onClick={startOllama} disabled={busy} icon={busy ? Loader2 : Play} spin={busy}>
                    {busy ? 'Starting…' : actionError ? 'Try again' : 'Start Ollama'}
                  </Primary>
                  <Ghost onClick={() => check(true)} disabled={busy || checking} icon={RefreshCw}>
                    Check again
                  </Ghost>
                </div>
              </Panel>
            )}

            {step === 'model' && status && (
              <Panel>
                <Heading
                  icon={Package}
                  title="Pull a first model"
                  text="Ollama is running with no models yet. Pick one; the download runs in the background and you can close this window."
                />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {status.suggested_models.map((m) => {
                    const selected = m.id === selectedModel
                    return (
                      <button
                        key={m.id}
                        type="button"
                        disabled={pullActive}
                        onClick={() => setSelectedModel(m.id)}
                        className="text-left px-3.5 py-3 rounded-xl border transition-colors disabled:opacity-60"
                        style={{
                          background: selected ? `${CYAN}0f` : 'rgba(6,10,26,0.5)',
                          borderColor: selected ? `${CYAN}55` : 'rgba(255,255,255,0.06)',
                        }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm text-white/85 font-medium truncate">{m.label}</span>
                          {m.size && <span className="text-[10px] text-white/35 shrink-0">{m.size}</span>}
                        </div>
                        <div className="text-[11px] font-mono text-white/40 truncate">{m.id}</div>
                        <div className="text-[11px] text-white/35 mt-0.5">{m.note}</div>
                      </button>
                    )
                  })}
                </div>

                {pull && (
                  <div className="rounded-xl bg-navy-900/50 border border-white/[0.06] px-3.5 py-3">
                    <div className="flex items-center justify-between text-xs text-white/60 mb-2">
                      <span className="font-mono truncate">{pull.model}</span>
                      <span>
                        {pull.status === 'completed'
                          ? 'Done'
                          : `${Math.round(pull.progress_pct)}%${
                              pull.total_bytes ? ` · ${fmtBytes(pull.completed_bytes)} / ${fmtBytes(pull.total_bytes)}` : ''
                            }`}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                      <motion.div
                        className="h-full rounded-full"
                        style={{ background: `linear-gradient(90deg, ${CYAN}, #8b5cf6)` }}
                        animate={{ width: `${Math.max(2, Math.min(100, pull.progress_pct))}%` }}
                        transition={{ ease: 'easeOut', duration: 0.4 }}
                      />
                    </div>
                  </div>
                )}

                {actionError && <ErrorBox text={actionError} />}

                <div className="flex flex-wrap items-center gap-2">
                  <Primary
                    onClick={startPull}
                    disabled={busy || !selectedModel}
                    icon={pullActive ? Loader2 : Download}
                    spin={pullActive}
                  >
                    {pullActive ? 'Downloading…' : `Pull ${selectedModel || 'model'}`}
                  </Primary>
                  <Ghost onClick={() => setStep('done')} disabled={pullActive}>
                    Skip for now
                  </Ghost>
                </div>
              </Panel>
            )}

            {step === 'done' && (
              <Panel>
                <div className="flex flex-col items-center text-center gap-3 py-2">
                  <div
                    className="w-14 h-14 rounded-2xl flex items-center justify-center"
                    style={{
                      background: 'linear-gradient(135deg, rgba(52,211,153,0.2), rgba(52,211,153,0.05))',
                      border: '1px solid rgba(52,211,153,0.35)',
                    }}
                  >
                    <CheckCircle2 size={26} className="text-emerald-300" />
                  </div>
                  <div>
                    <h3 className="text-white/90 font-semibold">Ollama is ready</h3>
                    <p className="text-xs text-white/45 mt-1">
                      {status?.service.reachable
                        ? `${status.service.url} · ${status.service.models} model${
                            status.service.models === 1 ? '' : 's'
                          } available through this gateway`
                        : 'The runtime is configured. Models appear here as soon as they finish downloading.'}
                    </p>
                  </div>
                  {status && status.service.model_names.length > 0 && (
                    <div className="flex flex-wrap justify-center gap-1.5 max-w-md">
                      {status.service.model_names.slice(0, 8).map((n) => (
                        <span
                          key={n}
                          className="px-2.5 py-1 rounded-full text-xs text-cyan-300 bg-cyan-400/10 border border-cyan-400/15"
                        >
                          {n}
                        </span>
                      ))}
                      {status.service.model_names.length > 8 && (
                        <span className="text-xs text-white/30 self-center">
                          +{status.service.model_names.length - 8} more
                        </span>
                      )}
                    </div>
                  )}
                  <div className="flex items-center gap-2 pt-2">
                    {onNavigate && (
                      <Primary
                        onClick={() => {
                          onNavigate('models')
                          onClose()
                        }}
                        icon={Package}
                      >
                        Open Models
                      </Primary>
                    )}
                    <Ghost onClick={onClose}>Close</Ghost>
                  </div>
                </div>
              </Panel>
            )}
          </div>

          {/* footer */}
          <div className="flex items-center justify-between gap-3 px-6 py-3 border-t border-white/5 bg-navy-900/30">
            <p className="text-[11px] text-white/30 flex items-center gap-1.5">
              <Terminal size={11} />
              Runs only on this machine. Only the official command shown is used, and nothing runs
              without your click.
            </p>
            {step !== 'done' && (
              <button
                onClick={onClose}
                className="text-xs text-white/50 hover:text-white/80 transition-colors shrink-0"
              >
                Close
              </button>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}

// ── building blocks ──────────────────────────────────────────────────────

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      className="space-y-4"
      initial={{ opacity: 0, x: 8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2 }}
    >
      {children}
    </motion.div>
  )
}

function Heading({
  icon: Icon,
  title,
  text,
  tone = 'normal',
}: {
  icon: typeof Server
  title: string
  text: string
  tone?: 'normal' | 'warn'
}) {
  return (
    <div className="flex items-start gap-3">
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
        style={{
          background: tone === 'warn' ? 'rgba(245,158,11,0.12)' : `${CYAN}12`,
          border: `1px solid ${tone === 'warn' ? 'rgba(245,158,11,0.3)' : `${CYAN}30`}`,
        }}
      >
        <Icon size={15} style={{ color: tone === 'warn' ? '#fbbf24' : CYAN }} />
      </div>
      <div>
        <h3 className="text-sm text-white/90 font-semibold">{title}</h3>
        <p className="text-xs text-white/45 leading-relaxed mt-0.5">{text}</p>
      </div>
    </div>
  )
}

function Fact({ ok, label, title }: { ok: boolean | null; label: string; title?: string }) {
  const color = ok === null ? 'rgba(255,255,255,0.45)' : ok ? '#34d399' : '#fbbf24'
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium"
      style={{ background: `${color}14`, border: `1px solid ${color}30`, color }}
    >
      {ok === null ? null : ok ? <Check size={11} /> : <AlertTriangle size={11} />}
      {label}
    </span>
  )
}

function Primary({
  children,
  onClick,
  disabled,
  icon: Icon,
  spin,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  icon?: typeof Server
  spin?: boolean
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
      style={{
        background: `linear-gradient(135deg, ${CYAN}26, rgba(139,92,246,0.2))`,
        border: `1px solid ${CYAN}40`,
        color: CYAN,
      }}
      whileHover={disabled ? undefined : { scale: 1.02 }}
      whileTap={disabled ? undefined : { scale: 0.98 }}
    >
      {Icon && <Icon size={14} className={spin ? 'animate-spin' : ''} />}
      {children}
    </motion.button>
  )
}

function Ghost({
  children,
  onClick,
  disabled,
  icon: Icon,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  icon?: typeof Server
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs text-white/65 bg-white/[0.04] border border-white/10 hover:bg-white/[0.07] hover:text-white/85 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {Icon && <Icon size={13} />}
      {children}
    </button>
  )
}

function Busy({ text, inline = false }: { text: string; inline?: boolean }) {
  return (
    <div className={`flex items-center gap-2 text-sm text-white/55 ${inline ? '' : 'justify-center py-10'}`}>
      <Loader2 size={inline ? 14 : 18} className="animate-spin" style={{ color: CYAN }} />
      <span className={inline ? 'text-xs' : ''}>{text}</span>
    </div>
  )
}

function ErrorBox({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="rounded-xl px-3.5 py-3 text-xs border text-red-300 bg-red-500/10 border-red-500/20">
      <div className="flex items-start gap-2">
        <AlertTriangle size={14} className="shrink-0 mt-0.5" />
        <span className="flex-1 break-words">{text}</span>
        {onRetry && (
          <button onClick={onRetry} className="underline underline-offset-2 hover:text-red-200 shrink-0">
            Retry
          </button>
        )}
      </div>
    </div>
  )
}

function Hint({ title, text, action }: { title: string; text: string; action?: React.ReactNode }) {
  return (
    <div className="rounded-xl px-3.5 py-3 border border-white/[0.06] bg-white/[0.02]">
      <div className="text-xs text-white/70 font-medium">{title}</div>
      <div className="text-[11px] text-white/40 leading-relaxed mt-0.5">{text}</div>
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

function CommandBox({
  command,
  caption,
  copied,
  onCopy,
}: {
  command: string
  caption: string
  copied: boolean
  onCopy: () => void
}) {
  if (!command) return null
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-white/30 mb-1.5">{caption}</div>
      <div className="flex items-center gap-2 rounded-xl bg-navy-900/70 border border-white/[0.08] px-3.5 py-2.5">
        <Terminal size={13} className="text-white/30 shrink-0" />
        <code className="flex-1 text-xs font-mono text-white/80 break-all">{command}</code>
        <button
          type="button"
          onClick={onCopy}
          className="p-1.5 rounded-md text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors shrink-0"
          aria-label="Copy command"
          title="Copy"
        >
          {copied ? <Check size={13} className="text-emerald-300" /> : <Copy size={13} />}
        </button>
      </div>
    </div>
  )
}

function LogConsole({
  lines,
  status,
  exitCode,
}: {
  lines: string[]
  status: OllamaSetupJob['status']
  exitCode: number | null
}) {
  const ref = useRef<HTMLPreElement>(null)
  useEffect(() => {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines.length])
  return (
    <div className="rounded-xl bg-black/40 border border-white/[0.08] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/[0.06] text-[10px] uppercase tracking-wider text-white/35">
        <span>Installer output</span>
        <span className={status === 'failed' ? 'text-red-300' : status === 'succeeded' ? 'text-emerald-300' : ''}>
          {status === 'running' ? 'running' : status === 'succeeded' ? 'finished' : `exit ${exitCode ?? '?'}`}
        </span>
      </div>
      <pre ref={ref} className="max-h-40 overflow-y-auto px-3 py-2 text-[11px] font-mono text-white/65 leading-relaxed whitespace-pre-wrap">
        {lines.length ? lines.join('\n') : 'Waiting for output…'}
      </pre>
    </div>
  )
}
