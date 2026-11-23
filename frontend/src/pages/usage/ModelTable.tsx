/** Models table: the core of the per-model usage view. */

import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Search } from 'lucide-react'
import type { DisplayCurrency, ModelUsage } from '../../lib/usageApi'
import { costLabel, filterModels, modelKey, percent, sortModels, tokensLabel, type SortKey } from './modelUsage'

const TREND = '#00e5ff'

/** Tiny daily trend. A flat line at the floor when nothing happened. */
export function Sparkline({ values, color = TREND, label }: { values: number[]; color?: string; label: string }) {
  const width = 72
  const height = 20
  const max = Math.max(...values, 0)
  const step = values.length > 1 ? width / (values.length - 1) : width
  const points = values.map((v, i) => `${(i * step).toFixed(1)},${(height - 2 - (max ? (v / max) * (height - 4) : 0)).toFixed(1)}`)
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="block">
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" opacity={max ? 0.9 : 0.25} />
    </svg>
  )
}

export function Badge({ tone = 'neutral', children, title }: { tone?: 'neutral' | 'warn' | 'muted'; children: React.ReactNode; title?: string }) {
  const tones = {
    neutral: 'border-white/10 text-white/55',
    warn: 'border-amber-400/30 text-amber-300/90',
    muted: 'border-white/10 text-white/40',
  }
  return (
    <span title={title} className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border bg-white/[0.03] whitespace-nowrap ${tones[tone]}`}>
      {children}
    </span>
  )
}

export function ModelBadges({ model }: { model: ModelUsage }) {
  const estimated = (model.measurement.estimated ?? 0) > 0
  return (
    <>
      {model.in_inventory === false && (
        <Badge tone="warn" title="Used in this period but not offered by the gateway now">
          Not in inventory
        </Badge>
      )}
      {model.runtime_unreachable && (
        <Badge tone="warn" title="Its runtime or provider could not be asked for its models">
          Runtime unreachable
        </Badge>
      )}
      {estimated && (
        <Badge tone="muted" title="Some token counts were approximated from text length">
          Estimated
        </Badge>
      )}
    </>
  )
}

const COLUMNS: { key: SortKey | null; label: string; className: string }[] = [
  { key: 'model', label: 'Model', className: 'text-left' },
  { key: 'total', label: 'Total', className: 'text-right' },
  { key: 'input', label: 'Input', className: 'text-right hidden md:table-cell' },
  { key: 'output', label: 'Output', className: 'text-right hidden md:table-cell' },
  { key: 'requests', label: 'Requests', className: 'text-right hidden sm:table-cell' },
  { key: 'failed', label: 'Failed', className: 'text-right' },
  { key: null, label: 'Trend', className: 'text-left hidden sm:table-cell pl-4' },
  { key: 'cost', label: 'Cost', className: 'text-right hidden lg:table-cell' },
]

export function ModelTable({
  models,
  colors,
  labels,
  currency,
  selected,
  onSelect,
}: {
  models: ModelUsage[]
  colors: Record<string, string>
  labels: Record<string, string>
  currency: DisplayCurrency
  selected: string | null
  onSelect: (key: string) => void
}) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'total', dir: 'desc' })
  const rows = useMemo(() => sortModels(filterModels(models, query), sort.key, sort.dir), [models, query, sort])

  const toggle = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'model' || key === 'provider' ? 'asc' : 'desc' }))

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-sm focus-within:border-glow-cyan/40 sm:max-w-xs">
        <Search size={14} className="text-white/40 shrink-0" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search models or providers"
          aria-label="Search models"
          className="w-full bg-transparent outline-none text-white/85 placeholder:text-white/30"
        />
      </label>

      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-sm">
          <thead className="text-xs text-white/45">
            <tr>
              {COLUMNS.map((col) => (
                <th key={col.label} className={`font-medium pb-2 px-1 ${col.className}`} aria-sort={col.key && sort.key === col.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}>
                  {col.key ? (
                    <button onClick={() => toggle(col.key!)} className="inline-flex items-center gap-1 hover:text-white/80">
                      {col.label}
                      {sort.key === col.key && (sort.dir === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const key = modelKey(m)
              const cost = costLabel(m.cost, currency)
              const failedTone = m.failed && m.failed / Math.max(m.requests, 1) >= 0.5 ? 'text-amber-300' : 'text-white/70'
              const trend = m.daily.tokens.some((v) => v > 0) ? m.daily.tokens : m.daily.requests
              return (
                <tr
                  key={key}
                  tabIndex={0}
                  onClick={() => onSelect(key)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelect(key)
                    }
                  }}
                  aria-selected={selected === key}
                  className={`border-t border-white/5 cursor-pointer outline-none transition-colors hover:bg-white/[0.03] focus-visible:bg-white/[0.05] ${
                    selected === key ? 'bg-glow-cyan/[0.06]' : ''
                  }`}
                >
                  <td className="py-2.5 px-1 min-w-0 max-w-[340px]">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="w-2 h-2 rounded-[2px] shrink-0" style={{ background: colors[labels[key]] ?? 'rgba(255,255,255,0.18)' }} />
                      <span className="text-white/90 break-all">{m.model}</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 mt-1 pl-4 text-xs text-white/40">
                      <span>{m.provider}</span>
                      {m.source_display_name && m.source_display_name.toLowerCase() !== m.provider && <span>· {m.source_display_name}</span>}
                      <ModelBadges model={m} />
                    </div>
                  </td>
                  <td className="py-2.5 px-1 text-right tabular-nums text-white/90" title={m.unknown_usage ? `${m.unknown_usage} requests without token counts` : undefined}>
                    {tokensLabel(m.tokens.total)}
                  </td>
                  <td className="py-2.5 px-1 text-right tabular-nums text-white/65 hidden md:table-cell">{tokensLabel(m.tokens.input)}</td>
                  <td className="py-2.5 px-1 text-right tabular-nums text-white/65 hidden md:table-cell">{tokensLabel(m.tokens.output)}</td>
                  <td className="py-2.5 px-1 text-right tabular-nums text-white/70 hidden sm:table-cell">{m.requests.toLocaleString()}</td>
                  <td className={`py-2.5 px-1 text-right tabular-nums ${failedTone}`}>
                    {m.failed ? (
                      <>
                        {m.failed.toLocaleString()}
                        <span className="text-white/35 text-xs"> {percent(m.failed, m.requests)}</span>
                      </>
                    ) : (
                      <span className="text-white/35">0</span>
                    )}
                  </td>
                  <td className="py-2.5 pl-4 pr-1 hidden sm:table-cell">
                    <Sparkline values={trend} color={colors[labels[key]]} label={`Daily trend for ${m.model}`} />
                  </td>
                  <td className={`py-2.5 px-1 text-right tabular-nums hidden lg:table-cell ${cost.muted ? 'text-white/45' : 'text-white/85'}`} title={cost.hint}>
                    {cost.text}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {rows.length === 0 && <p className="text-xs text-white/40 py-6 text-center">No model matches “{query}”.</p>}
      </div>
    </div>
  )
}
