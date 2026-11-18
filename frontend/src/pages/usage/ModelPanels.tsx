/** Inventory, sources and insights panels for the per-model usage view. */

import { useState } from 'react'
import { ArrowUpRight, Lightbulb, TriangleAlert, Unplug } from 'lucide-react'
import type { InventoryView, ModelInsight, ModelUsageView } from '../../lib/usageApi'
import { insightText, percent } from './modelUsage'
import { formatTokens } from './format'

function Count({ label, value, hint }: { label: string; value: number | null; hint?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-2xl font-semibold text-white/90 tabular-nums">{value === null ? '—' : value.toLocaleString()}</div>
      <div className="text-xs text-white/50">{label}</div>
      {hint && <div className="text-[11px] text-white/35 mt-0.5">{hint}</div>}
    </div>
  )
}

export function InventoryPanel({ inventory, onOpenModels }: { inventory: InventoryView; onOpenModels: () => void }) {
  const [open, setOpen] = useState(false)
  const sources = Object.entries(inventory.by_source)
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Count
          label="Available now"
          value={inventory.available}
          hint={sources.length ? sources.map(([s, n]) => `${s} ${n}`).join(' · ') : undefined}
        />
        <Count
          label="Used in period"
          value={inventory.used}
          hint={inventory.not_in_inventory ? `${inventory.not_in_inventory} no longer offered` : undefined}
        />
        <Count label="Never used in period" value={inventory.never_used} />
      </div>

      {inventory.unreachable.length > 0 && (
        <ul className="space-y-1">
          {inventory.unreachable.map((item) => (
            <li key={`${item.source}:${item.name}`} className="flex items-center gap-2 text-xs text-amber-300/90">
              <Unplug size={13} className="shrink-0" />
              {item.name}: not reachable, so its models aren’t counted here. Its usage still is.
            </li>
          ))}
        </ul>
      )}
      {inventory.available === null && inventory.unreachable.length === 0 && (
        <p className="text-xs text-white/45">The gateway’s model list could not be read.</p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        {inventory.never_used_models.length > 0 ? (
          <button onClick={() => setOpen(!open)} aria-expanded={open} className="text-xs text-white/55 hover:text-white/85">
            {open ? 'Hide' : 'Show'} models never used
          </button>
        ) : (
          <span />
        )}
        <button onClick={onOpenModels} className="inline-flex items-center gap-1 text-xs text-glow-cyan/80 hover:text-glow-cyan">
          Open the Models page <ArrowUpRight size={12} />
        </button>
      </div>
      {open && (
        <ul className="max-h-56 overflow-y-auto text-xs divide-y divide-white/5">
          {inventory.never_used_models.map((m) => (
            <li key={`${m.provider}:${m.model}`} className="flex justify-between gap-3 py-1.5">
              <span className="text-white/75 break-all">{m.model}</span>
              <span className="text-white/35 shrink-0">{[m.source_display_name, m.category?.replaceAll('_', ' ')].filter(Boolean).join(' · ')}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function SourcesPanel({ sources }: { sources: ModelUsageView['sources'] }) {
  if (!sources.attributed) {
    return (
      <p className="text-xs text-white/50 leading-relaxed">
        No request named its source yet. Send <code className="text-glow-cyan/90">X-OllaBridge-App: &lt;name&gt;</code> with your
        requests to see usage by app.
      </p>
    )
  }
  const max = Math.max(...sources.items.map((s) => s.tokens || s.events), 1)
  const totalEvents = sources.items.reduce((sum, s) => sum + s.events, 0)
  return (
    <ul className="space-y-3">
      {sources.items.map((s) => (
        <li key={s.key}>
          <div className="flex items-baseline justify-between text-xs mb-1 gap-3">
            <span className={s.attributed ? 'text-white/80' : 'text-white/45 italic'}>{s.attributed ? s.key : 'Unattributed'}</span>
            <span className="tabular-nums text-white/55">
              <span className="text-white/85">{formatTokens(s.tokens)}</span> · {s.events.toLocaleString()} req · {percent(s.events, totalEvents)}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-white/[0.06]">
            <div className="h-1.5 rounded-full bg-glow-cyan/70" style={{ width: `${Math.max(((s.tokens || s.events) / max) * 100, 1)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  )
}

export function ModelInsights({ insights, onSelect }: { insights: ModelInsight[]; onSelect: (provider: string, model: string) => void }) {
  if (!insights.length) return <p className="text-xs text-white/40 py-6 text-center">Nothing stands out in this period.</p>
  return (
    <ul className="max-h-[300px] overflow-y-auto -mr-2 pr-2">
      {insights.map((insight) => {
        const warning = insight.severity === 'warning'
        const Icon = warning ? TriangleAlert : Lightbulb
        const { title, detail } = insightText(insight)
        const clickable = insight.provider !== null && insight.model !== null
        const body = (
          <>
            <Icon size={16} className={`mt-0.5 shrink-0 ${warning ? 'text-amber-400' : 'text-glow-cyan/80'}`} />
            <div className="min-w-0 text-left">
              <p className="text-sm text-white/85 break-words">{title}</p>
              <p className="text-xs text-white/50 mt-0.5">{detail}</p>
            </div>
          </>
        )
        return (
          <li key={insight.id} className="border-t border-white/5 first:border-t-0">
            {clickable ? (
              <button onClick={() => onSelect(insight.provider!, insight.model!)} className="flex gap-3 py-3 w-full hover:bg-white/[0.02] rounded-md">
                {body}
              </button>
            ) : (
              <div className="flex gap-3 py-3">{body}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
