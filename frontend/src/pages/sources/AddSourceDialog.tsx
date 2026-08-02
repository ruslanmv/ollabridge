/**
 * Add-Source chooser.
 *
 * Replaces the old "Add Source opens the first catalog entry" behavior (which
 * made the provider depend on catalog ordering) with a searchable picker. This
 * is generic — it improves every provider, not one — so no source is named in
 * code here; labels and notes come from the backend catalog.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, Search, X } from 'lucide-react'
import type { AvailableSource } from '../../lib/api'
import { sourceUiProfile } from './sourceUiProfiles'

export function AddSourceDialog({
  available,
  onPick,
  onClose,
}: {
  available: AvailableSource[]
  onPick: (s: AvailableSource) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    searchRef.current?.focus()
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    const matches = available.filter(
      (s) =>
        !q ||
        s.label.toLowerCase().includes(q) ||
        s.notes.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q),
    )
    // Surface sources with a richer setup profile (e.g. dynamic discovery)
    // first, then the rest in catalog order.
    return [...matches].sort((a, b) => {
      const sa = sourceUiProfile(a.name).supportsDiscovery ? 0 : 1
      const sb = sourceUiProfile(b.name).supportsDiscovery ? 0 : 1
      return sa - sb
    })
  }, [available, query])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 backdrop-blur-sm p-4 pt-[10vh]"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl bg-navy-800 border border-white/10 shadow-2xl overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-label="Add an AI source"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <h2 className="text-sm font-semibold text-white">Add an AI source</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="p-1.5 rounded-md text-white/40 hover:text-white/70 hover:bg-white/5 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-6 pt-4">
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search sources…"
              className="w-full bg-navy-900/60 border border-white/10 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-glow-cyan/40 transition-colors"
            />
          </div>
        </div>

        <div className="px-3 py-3 max-h-[52vh] overflow-y-auto">
          {results.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-white/40">No sources match “{query}”.</p>
          ) : (
            <ul className="space-y-1">
              {results.map((s) => (
                <li key={s.name}>
                  <button
                    onClick={() => onPick(s)}
                    className="group w-full flex items-start gap-3 px-3 py-3 rounded-lg text-left hover:bg-white/5 border border-transparent hover:border-white/10 transition-colors"
                  >
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm font-medium text-white">{s.label}</span>
                      {s.notes && (
                        <span className="block text-xs text-white/45 mt-0.5 line-clamp-2">{s.notes}</span>
                      )}
                    </span>
                    <ArrowRight
                      size={16}
                      className="shrink-0 mt-0.5 text-white/20 group-hover:text-glow-cyan transition-colors"
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
