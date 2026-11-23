/** Models → Testing: check that models answer, one click, plain verdicts. */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ChevronDown, ChevronRight, Circle, Clock, Loader2, Play, Search, Square, XCircle } from 'lucide-react'
import type { Model } from '../../lib/api'
import { modelChecksApi, type ModelCheck } from '../../lib/modelChecksApi'
import { checkable, presetCount, runQueue, searchModels, seconds, sourceOf, summarize, toggleAll } from './modelTesting'

const SELECTION_KEY = 'ollabridge_model_test_selection'

function loadSelection(): Set<string> {
  try {
    const raw = localStorage.getItem(SELECTION_KEY)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

function saveSelection(selected: Set<string>) {
  try {
    localStorage.setItem(SELECTION_KEY, JSON.stringify([...selected]))
  } catch {
    // storage unavailable: the selection just isn't remembered
  }
}

function Result({ state, check }: { state: 'idle' | 'queued' | 'running'; check?: ModelCheck }) {
  if (state === 'running') {
    return (
      <span className="inline-flex items-center gap-1.5 text-white/60">
        <Loader2 size={14} className="animate-spin text-glow-cyan" /> Checking…
      </span>
    )
  }
  if (state === 'queued') {
    return (
      <span className="inline-flex items-center gap-1.5 text-white/40">
        <Clock size={14} /> Waiting
      </span>
    )
  }
  if (!check) {
    return (
      <span className="inline-flex items-center gap-1.5 text-white/35">
        <Circle size={14} /> Not checked yet
      </span>
    )
  }
  if (check.verdict === 'working') {
    return (
      <span className="inline-flex items-center gap-1.5 text-emerald-400">
        <CheckCircle2 size={14} /> Working
      </span>
    )
  }
  if (check.verdict === 'slow') {
    return (
      <span className="inline-flex items-center gap-1.5 text-amber-300">
        <Clock size={14} /> Slow
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-red-400">
      <XCircle size={14} /> Not working
    </span>
  )
}

function when(iso: string | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  const today = new Date().toDateString() === date.toDateString()
  return today
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function TestingTab({ models }: { models: Model[] }) {
  const queryClient = useQueryClient()
  const last = useQuery({ queryKey: ['model-checks'], queryFn: modelChecksApi.last, retry: false })
  const [results, setResults] = useState<Record<string, ModelCheck>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [running, setRunning] = useState<Set<string>>(new Set())
  const [queued, setQueued] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Set<string>>(loadSelection)
  const [includePresets, setIncludePresets] = useState(false)
  const [query, setQuery] = useState('')
  const [source, setSource] = useState('')
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [runIds, setRunIds] = useState<string[]>([])
  const stop = useRef({ aborted: false })
  const busy = running.size > 0 || queued.size > 0

  useEffect(() => saveSelection(selected), [selected])

  const all = useMemo(() => checkable(models, includePresets), [models, includePresets])
  const visible = useMemo(() => searchModels(all, query, source), [all, query, source])
  const sources = useMemo(() => [...new Set(all.map(sourceOf))].sort(), [all])
  const presets = presetCount(models)
  const merged = { ...(last.data?.items ?? {}), ...results }
  const runResults = runIds.map((id) => merged[id]).filter(Boolean) as ModelCheck[]
  const summary = summarize(runIds.length ? runResults : all.map((m) => merged[m.id]).filter(Boolean) as ModelCheck[])
  const lastRun = (runIds.length ? runResults : Object.values(merged))
    .map((r) => r.checked_at)
    .sort()
    .at(-1)

  const run = async (ids: string[]) => {
    if (!ids.length || busy) return
    stop.current = { aborted: false }
    setRunIds(ids)
    setQueued(new Set(ids))
    await runQueue(
      ids,
      async (id) => {
        setQueued((q) => {
          const n = new Set(q)
          n.delete(id)
          return n
        })
        setRunning((r) => new Set(r).add(id))
        try {
          const result = await modelChecksApi.check(id)
          setResults((prev) => ({ ...prev, [id]: result }))
          setErrors((prev) => {
            const n = { ...prev }
            delete n[id]
            return n
          })
        } catch (err) {
          setErrors((prev) => ({ ...prev, [id]: (err as Error).message }))
        } finally {
          setRunning((r) => {
            const n = new Set(r)
            n.delete(id)
            return n
          })
        }
      },
      undefined,
      stop.current,
    )
    setQueued(new Set())
    queryClient.invalidateQueries({ queryKey: ['model-checks'] })
  }

  const visibleIds = visible.map((m) => m.id)
  const allVisibleOn = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id))
  const selectedIds = all.map((m) => m.id).filter((id) => selected.has(id))
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })

  return (
    <div className="space-y-4">
      <p className="text-sm text-white/50">
        Check that your models answer. Each one gets a tiny test message, nothing you've written is used.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => run(all.map((m) => m.id))}
          disabled={busy || all.length === 0}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-glow-cyan/15 text-glow-cyan border border-glow-cyan/25 disabled:opacity-40"
        >
          <Play size={14} /> Check all {all.length}
        </button>
        <button
          onClick={() => run(selectedIds)}
          disabled={busy || selectedIds.length === 0}
          className="px-4 py-2 rounded-xl text-sm text-white/75 bg-white/5 border border-white/10 hover:text-white/90 disabled:opacity-40"
        >
          Check selected ({selectedIds.length})
        </button>
        {busy && (
          <button
            onClick={() => {
              stop.current.aborted = true
              setQueued(new Set())
            }}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm text-white/75 bg-white/5 border border-white/10 hover:text-white/90"
          >
            <Square size={12} /> Stop
          </button>
        )}
        <div className="flex-1" />
        <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm w-full sm:w-56 focus-within:border-glow-cyan/40">
          <Search size={14} className="text-white/30 shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search models"
            aria-label="Search models to check"
            className="w-full bg-transparent outline-none text-white/80 placeholder:text-white/25"
          />
        </label>
        {sources.length > 1 && (
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            aria-label="Filter by source"
            className="rounded-xl bg-navy-800 border border-white/10 px-3 py-2 text-sm text-white/75 outline-none"
          >
            <option value="">All sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
      </div>

      {presets > 0 && (
        <label className="flex items-center gap-2 text-xs text-white/50 select-none">
          <input type="checkbox" checked={includePresets} onChange={(e) => setIncludePresets(e.target.checked)} className="accent-cyan-400" />
          Show presets and personas ({presets}). They run on a base model, so checking the base model usually covers them.
        </label>
      )}

      {summary.checked > 0 && (
        <div className="glass-card-sm px-4 py-3 text-sm space-y-1" role="status">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <span className="text-emerald-400">✓ {summary.working} working</span>
            {summary.slow > 0 && <span className="text-amber-300">◷ {summary.slow} slow</span>}
            <span className={summary.notWorking ? 'text-red-400' : 'text-white/40'}>✕ {summary.notWorking} not working</span>
            {lastRun && <span className="text-white/35">last check {when(lastRun)}</span>}
          </div>
          {summary.sharedCause && <p className="text-amber-300/90 text-xs">{summary.sharedCause}</p>}
        </div>
      )}

      {last.isError && <p className="text-xs text-amber-300/90">Earlier results couldn't be loaded. New checks still work.</p>}

      <div className="glass-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-white/45 border-b border-white/5">
            <tr>
              <th className="w-10 px-3 py-2.5">
                <input
                  type="checkbox"
                  aria-label="Select all shown models"
                  checked={allVisibleOn}
                  onChange={() => setSelected((s) => toggleAll(s, visibleIds))}
                  className="accent-cyan-400"
                />
              </th>
              <th className="text-left font-medium py-2.5 pr-3">Model</th>
              <th className="text-left font-medium py-2.5 pr-3 hidden sm:table-cell">Source</th>
              <th className="text-left font-medium py-2.5 pr-3">Result</th>
              <th className="text-right font-medium py-2.5 pr-3">Time</th>
              <th className="text-right font-medium py-2.5 pr-3 hidden sm:table-cell">When</th>
              <th className="w-16 hidden sm:table-cell" />
            </tr>
          </thead>
          <tbody>
            {visible.map((m) => {
              const check = merged[m.id]
              const state = running.has(m.id) ? 'running' : queued.has(m.id) ? 'queued' : 'idle'
              const error = errors[m.id]
              const expanded = open.has(m.id)
              const explain = state === 'idle' && (error || (check && check.verdict !== 'working') || check?.reason_code === 'empty_answer')
              return (
                <tr key={m.id} className="border-t border-white/5 align-top">
                  <td className="px-3 py-3">
                    <input
                      type="checkbox"
                      aria-label={`Select ${m.id}`}
                      checked={selected.has(m.id)}
                      onChange={() => toggle(m.id)}
                      className="accent-cyan-400"
                    />
                  </td>
                  <td className="py-3 pr-3 min-w-0">
                    <div className="text-white/85 break-all">{m.id}</div>
                    <div className="text-xs text-white/35 sm:hidden">
                      {sourceOf(m)}
                      {check && ` · ${when(check.checked_at)}`}
                    </div>
                    {explain && (
                      <div className="mt-1.5 text-xs">
                        <p className={error || check?.verdict === 'not_working' ? 'text-red-300/90' : 'text-white/55'}>
                          {error ? `The check itself couldn't run: ${error}` : check!.plain}
                        </p>
                        {check?.detail && !error && (
                          <>
                            <button
                              onClick={() =>
                                setOpen((o) => {
                                  const n = new Set(o)
                                  if (n.has(m.id)) n.delete(m.id)
                                  else n.add(m.id)
                                  return n
                                })
                              }
                              aria-expanded={expanded}
                              className="inline-flex items-center gap-0.5 mt-1 text-white/40 hover:text-white/70"
                            >
                              {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />} Details
                            </button>
                            {expanded && (
                              <p className="mt-1 font-mono text-[11px] text-white/45 break-all">
                                {check.reason_code} · {check.detail}
                              </p>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="py-3 pr-3 text-white/55 hidden sm:table-cell">{sourceOf(m)}</td>
                  <td className="py-3 pr-3 whitespace-nowrap">
                    <Result state={state} check={check} />
                  </td>
                  <td className="py-3 pr-3 text-right tabular-nums text-white/65 whitespace-nowrap">{state === 'idle' && check ? seconds(check.latency_ms) : ''}</td>
                  <td className="py-3 pr-3 text-right text-white/40 hidden sm:table-cell whitespace-nowrap">{state === 'idle' ? when(check?.checked_at) : ''}</td>
                  <td className="py-3 pr-3 text-right hidden sm:table-cell">
                    <button
                      onClick={() => run([m.id])}
                      disabled={busy}
                      className="text-xs text-glow-cyan/80 hover:text-glow-cyan disabled:opacity-30"
                    >
                      Check
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {visible.length === 0 && (
          <p className="text-xs text-white/40 py-8 text-center">{all.length ? 'No model matches.' : 'No models to check yet.'}</p>
        )}
      </div>
    </div>
  )
}
