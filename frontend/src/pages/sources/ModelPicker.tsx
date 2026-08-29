import { useMemo, useState } from 'react'
import { Loader2, RefreshCw, Search, Sparkles, Check, AlertCircle } from 'lucide-react'
import type { SourceModel } from '../../lib/api'
import { useSourceModels } from '../../lib/hooks'

/**
 * The source's live model catalog, rendered as a picker for its default model.
 *
 * The list is what the *saved key* can actually reach, fetched from
 * `/admin/sources/{name}/models` — never a hard-coded catalog, which is how
 * the settings form kept offering models the provider had decommissioned.
 * Free-tier models are badged and shown first, because a source with no
 * explicit choice defaults to one of them.
 */
export function ModelPicker({
  name,
  enabled,
  value,
  onSelect,
}: {
  /** Source name, e.g. "groq". */
  name: string
  /** False while the source has no key yet — nothing to discover with. */
  enabled: boolean
  /** Currently selected model id, if any. */
  value: string
  onSelect: (modelId: string) => void
}) {
  const [search, setSearch] = useState('')
  // null = follow the catalog: filter to free models when the provider has
  // any. A provider that bills for everything (watsonx) would otherwise open
  // on an empty list behind a filter the user never asked for.
  const [freeOnlyChoice, setFreeOnlyChoice] = useState<boolean | null>(null)
  const query = useSourceModels(name, { enabled })

  const summary = query.data?.summary
  const freeCount = summary?.free ?? 0
  const hasFreeTier = freeCount > 0
  const freeOnly = freeOnlyChoice ?? hasFreeTier

  const models = useMemo(() => {
    const all = query.data?.models ?? []
    // An embedding or safety-guard model is a real part of the catalog but
    // never a chat default, so it is listed last rather than hidden. Same for
    // a model the provider has marked deprecated.
    const chatFirst = [...all].sort((a, b) => {
      const rank = (m: SourceModel) =>
        (m.category === 'chat' ? 0 : 4) + (m.deprecated ? 2 : 0) + (m.free ? 0 : 1)
      return rank(a) - rank(b) || String(a.id).localeCompare(String(b.id))
    })
    const q = search.trim().toLowerCase()
    return chatFirst.filter(
      (m) =>
        (!freeOnly || m.free) &&
        (!q ||
          String(m.id).toLowerCase().includes(q) ||
          String(m.name ?? '').toLowerCase().includes(q)),
    )
  }, [query.data, search, freeOnly])

  if (!enabled) {
    return (
      <p className="text-[11px] text-white/30">
        Save an API key to list the models this source can reach.
      </p>
    )
  }

  return (
    <div className="rounded-lg border border-white/8 bg-navy-900/40">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-2.5 py-2 border-b border-white/5">
        <div className="relative flex-1 min-w-0">
          <Search
            size={12}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-white/25"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search models"
            spellCheck={false}
            aria-label="Search available models"
            className="w-full bg-transparent pl-6 pr-2 py-1 text-xs text-white placeholder:text-white/25 focus:outline-none"
          />
        </div>
        {hasFreeTier && (
          <button
            type="button"
            onClick={() => setFreeOnlyChoice(!freeOnly)}
            aria-pressed={freeOnly}
            className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[10px] font-medium transition-colors"
            style={{
              background: freeOnly ? 'rgba(20,184,166,0.12)' : 'rgba(255,255,255,0.02)',
              borderColor: freeOnly ? 'rgba(20,184,166,0.35)' : 'rgba(255,255,255,0.08)',
              color: freeOnly ? '#5eead4' : 'rgba(255,255,255,0.5)',
            }}
          >
            <Sparkles size={10} /> Free only
          </button>
        )}
        <button
          type="button"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
          aria-label="Refresh model list"
          className="shrink-0 p-1 rounded-md text-white/35 hover:text-white/70 hover:bg-white/5 transition-colors disabled:opacity-40"
        >
          <RefreshCw size={12} className={query.isFetching ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Body */}
      {query.isLoading ? (
        <div className="flex items-center gap-2 px-3 py-4 text-xs text-white/40">
          <Loader2 size={13} className="animate-spin" /> Fetching available models…
        </div>
      ) : query.isError ? (
        <div className="flex items-start gap-2 px-3 py-3 text-xs text-amber-300/90">
          <AlertCircle size={13} className="shrink-0 mt-0.5" />
          <span>
            Could not list models — {(query.error as Error).message}. You can still
            type a model id above.
          </span>
        </div>
      ) : models.length === 0 ? (
        <p className="px-3 py-3 text-xs text-white/40">
          {freeOnly && freeCount === 0
            ? 'No free-tier models in this catalog. Turn off “Free only” to see the rest.'
            : 'No models match.'}
        </p>
      ) : (
        <ul className="max-h-52 overflow-y-auto py-1" role="listbox">
          {models.map((m) => {
            const active = m.id === value
            return (
              <li key={m.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => onSelect(String(m.id))}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-white/5 transition-colors"
                  style={{ background: active ? 'rgba(0,229,255,0.08)' : undefined }}
                >
                  <Check
                    size={12}
                    className={active ? 'text-glow-cyan' : 'text-transparent'}
                  />
                  <span className="flex-1 min-w-0">
                    <span className="block truncate font-mono text-xs text-white/85">
                      {m.id}
                    </span>
                    {m.category && m.category !== 'chat' && (
                      <span className="block text-[10px] text-white/30">
                        {m.category}
                      </span>
                    )}
                  </span>
                  {m.deprecated && (
                    <span
                      title="The provider has scheduled this model for retirement"
                      className="shrink-0 px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wide bg-amber-400/10 text-amber-300 border border-amber-400/25"
                    >
                      Deprecated
                    </span>
                  )}
                  {m.free && (
                    <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wide bg-teal-400/10 text-teal-300 border border-teal-400/25">
                      Free
                    </span>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {summary && (
        <div className="px-3 py-1.5 border-t border-white/5 text-[10px] text-white/35">
          {summary.count} model{summary.count === 1 ? '' : 's'} reachable with this
          key{hasFreeTier ? ` · ${freeCount} free` : ''}
        </div>
      )}
    </div>
  )
}
