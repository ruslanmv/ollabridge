/** Detail sheet for one model: right-hand panel on desktop, full screen on mobile. */

import { useEffect, useState } from 'react'
import { ArrowUpRight, X } from 'lucide-react'
import type { DisplayCurrency, ModelUsage, ModelUsageView } from '../../lib/usageApi'
import { StackedColumns } from './charts'
import { ModelBadges } from './ModelTable'
import { costLabel, humanize, percent, tokensLabel } from './modelUsage'

const INPUT_COLOR = '#3987e5'
const OUTPUT_COLOR = '#00e5ff'

const DIMENSION_LABELS: Record<string, string> = {
  input_tokens: 'Input',
  cache_read_tokens: 'Cache read',
  cache_write_tokens: 'Cache write',
  output_tokens: 'Output',
  reasoning_tokens: 'Reasoning',
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0" title={hint}>
      <div className="text-[11px] text-white/45">{label}</div>
      <div className="text-lg font-semibold text-white/90 tabular-nums truncate">{value}</div>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 border-t border-white/5 first:border-t-0 text-xs">
      <dt className="text-white/45 shrink-0">{label}</dt>
      <dd className="text-white/80 text-right min-w-0 break-all">{children}</dd>
    </div>
  )
}

export function ModelDetail({
  model,
  view,
  color,
  currency,
  onClose,
  onOpenModels,
}: {
  model: ModelUsage
  view: ModelUsageView
  color: string
  currency: DisplayCurrency
  onClose: () => void
  onOpenModels: () => void
}) {
  const [metric, setMetric] = useState<'tokens' | 'requests'>(() => (model.tokens.total ? 'tokens' : 'requests'))
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const cost = costLabel(model.cost, currency)
  const input = model.tokens.input ?? 0
  const output = model.tokens.output ?? 0
  const split = input + output
  const dims = Object.entries(model.tokens.dimensions).filter(([, v]) => v)
  const measured = Object.entries(model.measurement).filter(([, n]) => n > 0)
  const series = {
    metric: metric === 'requests' ? ('events' as const) : ('tokens' as const),
    group_by: 'model',
    days: view.days,
    series: [{ key: model.model, values: model.daily[metric], total: model.daily[metric].reduce((a, b) => a + b, 0) }],
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={`Usage of ${model.model}`}>
      <button aria-label="Close" onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-[1px] cursor-default" />
      <aside className="relative h-full w-full sm:w-[440px] bg-navy-800 border-l border-white/10 shadow-2xl overflow-y-auto">
        <header className="sticky top-0 bg-navy-800/95 backdrop-blur px-5 pt-5 pb-4 border-b border-white/5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-white/95 break-all">{model.model}</h2>
              <p className="text-xs text-white/45 mt-1">
                {model.provider}
                {model.source_display_name && ` · ${model.source_display_name}`}
              </p>
              <div className="flex flex-wrap gap-1.5 mt-2">
                <ModelBadges model={model} />
              </div>
            </div>
            <button onClick={onClose} aria-label="Close details" className="p-1 rounded-md text-white/50 hover:text-white/90 hover:bg-white/5">
              <X size={16} />
            </button>
          </div>
        </header>

        <div className="p-5 space-y-6">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Total tokens" value={tokensLabel(model.tokens.total)} hint={model.unknown_usage ? `${model.unknown_usage} requests without token counts` : undefined} />
            <Stat label="Requests" value={model.requests.toLocaleString()} />
            <Stat label="Failed" value={model.failed ? `${model.failed} · ${percent(model.failed, model.requests)}` : '0'} />
          </div>

          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-medium text-white/70">Over time</h3>
              <div role="group" aria-label="Metric" className="inline-flex rounded-md border border-white/10 p-0.5 text-[11px]">
                {(['tokens', 'requests'] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMetric(m)}
                    aria-pressed={metric === m}
                    className={`px-2 py-0.5 rounded ${metric === m ? 'bg-glow-cyan/15 text-glow-cyan' : 'text-white/50 hover:text-white/80'}`}
                  >
                    {m === 'tokens' ? 'Tokens' : 'Requests'}
                  </button>
                ))}
              </div>
            </div>
            <StackedColumns data={series} colors={{ [model.model]: color }} currency={currency} />
          </section>

          <section>
            <h3 className="text-xs font-medium text-white/70 mb-2">Input and output</h3>
            {split > 0 ? (
              <>
                <div className="flex h-2 rounded-full overflow-hidden bg-white/[0.06]" title={`Input ${percent(input, split)}, output ${percent(output, split)}`}>
                  <div style={{ width: `${(input / split) * 100}%`, background: INPUT_COLOR }} />
                  <div style={{ width: `${(output / split) * 100}%`, background: OUTPUT_COLOR }} />
                </div>
                <div className="flex justify-between text-xs mt-1.5 text-white/60">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-[2px]" style={{ background: INPUT_COLOR }} />
                    Input {tokensLabel(model.tokens.input)} · {percent(input, split)}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-[2px]" style={{ background: OUTPUT_COLOR }} />
                    Output {tokensLabel(model.tokens.output)} · {percent(output, split)}
                  </span>
                </div>
                {dims.length > 2 && (
                  <dl className="mt-3">
                    {dims.map(([d, v]) => (
                      <Row key={d} label={DIMENSION_LABELS[d] ?? humanize(d)}>
                        {tokensLabel(v)}
                      </Row>
                    ))}
                  </dl>
                )}
              </>
            ) : (
              <p className="text-xs text-white/40">No token counts were recorded for this model in this period.</p>
            )}
          </section>

          {model.failed > 0 && (
            <section>
              <h3 className="text-xs font-medium text-white/70 mb-2">Failures</h3>
              <dl>
                {Object.entries(model.errors).map(([category, n]) => (
                  <Row key={category} label={humanize(category)}>
                    {n.toLocaleString()} · {percent(n, model.requests)} of requests
                  </Row>
                ))}
              </dl>
            </section>
          )}

          <section>
            <h3 className="text-xs font-medium text-white/70 mb-2">Details</h3>
            <dl>
              <Row label="Provider">{model.provider}</Row>
              {model.source_display_name && <Row label="Runtime">{model.source_display_name}</Row>}
              {model.execution.length > 0 && <Row label="Runs on">{model.execution.map(humanize).join(', ')}</Row>}
              {model.billing_providers.length > 0 && <Row label="Billed by">{model.billing_providers.join(', ')}</Row>}
              <Row label="Cost">
                <span title={cost.hint}>{cost.text}</span>
                {model.cost.modes.length > 0 && model.cost.state !== 'not_billed' && (
                  <span className="text-white/40"> · {model.cost.modes.map(humanize).join(', ')}</span>
                )}
              </Row>
              {measured.length > 0 && (
                <Row label="Measured as">{measured.map(([m, n]) => `${humanize(m)} ${percent(n, model.requests)}`).join(', ')}</Row>
              )}
              {Object.keys(model.requested_as).length > 0 && (
                <Row label="Requested as">
                  {Object.entries(model.requested_as)
                    .map(([alias, n]) => `${alias} (${n})`)
                    .join(', ')}
                </Row>
              )}
              <Row label="Average latency">{model.avg_latency_ms === null ? '—' : `${(model.avg_latency_ms / 1000).toFixed(1)} s`}</Row>
              <Row label="Last request">{model.last_seen ? new Date(model.last_seen).toLocaleString() : '—'}</Row>
              <Row label="In inventory">{model.in_inventory === null ? 'Could not check' : model.in_inventory ? 'Yes' : 'No'}</Row>
            </dl>
          </section>

          <button onClick={onOpenModels} className="inline-flex items-center gap-1 text-xs text-glow-cyan/80 hover:text-glow-cyan">
            Open the Models page <ArrowUpRight size={12} />
          </button>
        </div>
      </aside>
    </div>
  )
}
