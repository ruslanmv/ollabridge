/**
 * Usage & Cost — tokens, spend and attribution for everything this gateway
 * served, plus Claude Code telemetry. Reads /v1/bi/* (usage/routes.py).
 *
 * Every figure says how it was measured (verified / observed / estimated), and
 * subscription usage is shown as an API-equivalent, never as spend.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  Bot,
  Coins,
  Lightbulb,
  Receipt,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  Wallet,
} from 'lucide-react'
import { usageApi, type Kpi, type MeasurementMix, type UsageInsight } from '../../lib/usageApi'
import { Legend, SeriesTable, ShareList, StackedColumns } from './charts'
import { assignColors, formatTokens, formatUsd } from './format'

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
]

const BADGES: Record<string, { label: string; hint: string }> = {
  verified: { label: 'verified', hint: 'Reported by the provider' },
  observed: { label: 'observed', hint: 'Counted locally (Ollama runtime, Claude Code telemetry)' },
  estimated: { label: 'estimated', hint: 'Approximated from text length' },
}

function useUsage(days: number, metric: 'tokens' | 'cost') {
  const options = { refetchInterval: 30_000, retry: false } as const
  return {
    overview: useQuery({ queryKey: ['usage', 'overview', days], queryFn: () => usageApi.overview(days), ...options }),
    series: useQuery({
      queryKey: ['usage', 'series', days, metric],
      queryFn: () => usageApi.timeseries(days, metric),
      ...options,
    }),
    share: useQuery({
      queryKey: ['usage', 'share', days, metric],
      queryFn: () => usageApi.breakdown(days, metric),
      ...options,
    }),
    agents: useQuery({ queryKey: ['usage', 'agents', days], queryFn: () => usageApi.agents(days), ...options }),
    insights: useQuery({ queryKey: ['usage', 'insights', days], queryFn: () => usageApi.insights(days), ...options }),
    sources: useQuery({ queryKey: ['usage', 'sources'], queryFn: usageApi.sources, ...options }),
  }
}

function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
  label: string
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-white/10 p-0.5 bg-white/[0.03]">
      {options.map((option) => (
        <button
          key={String(option.value)}
          onClick={() => onChange(option.value)}
          aria-pressed={option.value === value}
          className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
            option.value === value ? 'bg-glow-cyan/15 text-glow-cyan' : 'text-white/50 hover:text-white/80'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function Delta({ kpi, invert = false }: { kpi: Pick<Kpi, 'delta_pct'>; invert?: boolean }) {
  if (kpi.delta_pct === null) return <span className="text-xs text-white/35">no prior period</span>
  const up = kpi.delta_pct >= 0
  // For spend, up is not good news; colour is reserved for that judgement.
  const good = invert ? !up : up
  const Icon = up ? TrendingUp : TrendingDown
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${good ? 'text-emerald-400' : 'text-amber-400'}`}>
      <Icon size={12} />
      {up ? '+' : ''}
      {kpi.delta_pct}%<span className="text-white/35"> vs prior period</span>
    </span>
  )
}

function MixBadges({ mix }: { mix: MeasurementMix }) {
  const parts = (['verified', 'observed', 'estimated'] as const).filter((key) => (mix[key] ?? 0) > 0)
  if (!parts.length) return null
  return (
    <div className="flex flex-wrap gap-1">
      {parts.map((key) => (
        <span
          key={key}
          title={BADGES[key].hint}
          className="px-1.5 py-0.5 rounded text-[10px] border border-white/10 text-white/55 bg-white/[0.03]"
        >
          {Math.round((mix[key] ?? 0) * 100)}% {BADGES[key].label}
        </span>
      ))}
    </div>
  )
}

function Tile({
  icon: Icon,
  label,
  value,
  children,
}: {
  icon: typeof Coins
  label: string
  value: string
  children?: React.ReactNode
}) {
  return (
    <div className="glass-card-sm p-4 flex flex-col gap-1.5 min-w-0">
      <div className="flex items-center gap-2 text-xs text-white/55">
        <Icon size={14} className="text-white/40 shrink-0" />
        {label}
      </div>
      <div className="text-2xl font-semibold text-white/95 tabular-nums truncate">{value}</div>
      <div className="min-h-[18px] flex flex-col gap-1">{children}</div>
    </div>
  )
}

function Panel({
  title,
  action,
  children,
  className = '',
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={`glass-card p-5 min-w-0 ${className}`}>
      <div className="flex items-center justify-between gap-3 mb-4">
        <h2 className="text-sm font-semibold text-white/90">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-white/40 py-6 text-center">{children}</p>
}

function BudgetTile({ overview }: { overview: NonNullable<ReturnType<typeof useUsage>['overview']['data']> }) {
  const client = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const save = useMutation({
    mutationFn: (usd: number) => usageApi.setBudget(usd > 0 ? Math.round(usd * 1_000_000) : null),
    onSuccess: () => {
      setEditing(false)
      client.invalidateQueries({ queryKey: ['usage', 'overview'] })
    },
  })
  const budget = overview.budget

  if (editing) {
    return (
      <Tile icon={Wallet} label="Monthly budget (USD)" value="">
        <form
          className="flex gap-2 -mt-8"
          onSubmit={(event) => {
            event.preventDefault()
            save.mutate(Number(draft) || 0)
          }}
        >
          <input
            autoFocus
            type="number"
            min="0"
            step="0.01"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="0 removes it"
            className="w-full rounded-md bg-white/5 border border-white/10 px-2 py-1 text-sm text-white/90 outline-none focus:border-glow-cyan/50"
          />
          <button type="submit" className="px-2 py-1 rounded-md text-xs bg-glow-cyan/15 text-glow-cyan">
            Save
          </button>
        </form>
      </Tile>
    )
  }

  return (
    <Tile icon={Wallet} label="Budget remaining" value={budget ? formatUsd(budget.remaining_micro) : '—'}>
      {budget ? (
        <>
          <div className="h-1.5 rounded-full bg-white/[0.06]" title={`${budget.remaining_pct}% of the monthly budget left`}>
            <div
              className={`h-1.5 rounded-full ${budget.remaining_micro < 0 ? 'bg-red-400' : 'bg-[#3987e5]'}`}
              style={{ width: `${Math.min(Math.max(100 - budget.remaining_pct, 0), 100)}%` }}
            />
          </div>
          <span className="text-xs text-white/45">
            {formatUsd(budget.spent_micro)} of {formatUsd(budget.limit_micro)} this month
            {budget.projected_overrun && <span className="text-amber-400"> · on course to exceed</span>}
          </span>
        </>
      ) : (
        <span className="text-xs text-white/40">No monthly budget set</span>
      )}
      <button
        onClick={() => {
          setDraft(budget ? String(budget.limit_micro / 1_000_000) : '')
          setEditing(true)
        }}
        className="self-start text-xs text-glow-cyan/80 hover:text-glow-cyan"
      >
        {budget ? 'Change' : 'Set budget'}
      </button>
    </Tile>
  )
}

function InsightRow({ insight }: { insight: UsageInsight }) {
  const warning = insight.severity === 'warning'
  const Icon = warning ? TriangleAlert : Lightbulb
  return (
    <li className="flex gap-3 py-3 border-t border-white/5 first:border-t-0 first:pt-0">
      <Icon size={16} className={`mt-0.5 shrink-0 ${warning ? 'text-amber-400' : 'text-glow-cyan/80'}`} />
      <div className="min-w-0">
        <p className="text-sm text-white/85">{insight.title}</p>
        <p className="text-xs text-white/50 mt-0.5">{insight.detail}</p>
        {insight.estimated_saving_micro ? (
          <p className="text-xs text-white/60 mt-0.5">Spent on these: {formatUsd(insight.estimated_saving_micro)}</p>
        ) : null}
      </div>
    </li>
  )
}

export function UsagePage() {
  const [days, setDays] = useState(30)
  const [metric, setMetric] = useState<'tokens' | 'cost'>('tokens')
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const { overview, series, share, agents, insights, sources } = useUsage(days, metric)

  const data = overview.data
  const seriesKeys = series.data?.series.map((s) => s.key) ?? []
  // One assignment for every provider on the page, so a provider wears the
  // same colour in the chart, the share list and the agents table.
  const colors = assignColors([
    ...new Set([
      ...seriesKeys,
      ...(share.data?.items.map((item) => item.key) ?? []),
      ...(agents.data?.items.map((agent) => agent.top_provider) ?? []),
    ]),
  ])
  const hasUsage = (data?.requests.value ?? 0) > 0

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-[1280px] mx-auto space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-white/50">
            Tokens, cost and attribution for requests through this gateway. Metadata only — no prompt content.
          </p>
          <Segmented
            label="Period"
            value={days}
            onChange={setDays}
            options={RANGES.map((r) => ({ value: r.days, label: r.label }))}
          />
        </div>

        {overview.isError && (
          <div className="glass-card-sm p-4 text-sm text-amber-300/90">
            Could not load usage: {(overview.error as Error).message}
          </div>
        )}

        {data && (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <Tile icon={Activity} label="Total tokens" value={formatTokens(data.total_tokens.value)}>
              <Delta kpi={data.total_tokens} />
              <MixBadges mix={data.total_tokens.measurement_mix} />
            </Tile>
            <Tile icon={Coins} label="Estimated cost" value={formatUsd(data.estimated_cost_micro.value)}>
              <Delta kpi={data.estimated_cost_micro} invert />
              {data.estimated_cost_micro.unpriced_tokens > 0 && (
                <span className="text-xs text-amber-400/90" title="Add prices for these models to the price catalog">
                  Lower bound: {formatTokens(data.estimated_cost_micro.unpriced_tokens)} tokens unpriced
                </span>
              )}
              {data.subscription_equivalent_micro.value > 0 && (
                <span className="text-xs text-white/45" title="What subscription usage would cost at API prices. Not a charge.">
                  + {formatUsd(data.subscription_equivalent_micro.value)} subscription-equivalent
                </span>
              )}
            </Tile>
            <Tile icon={Receipt} label="Billed cost" value={formatUsd(data.billed_cost_micro.value)}>
              <Delta kpi={data.billed_cost_micro} invert />
              <span className="text-xs text-white/40">Charges stated by providers</span>
            </Tile>
            <Tile icon={Bot} label="Active agents" value={String(data.active_agents.value)}>
              <span className="text-xs text-white/45">
                {data.active_agents.delta >= 0 ? '+' : ''}
                {data.active_agents.delta} vs prior period
              </span>
              <span className="text-xs text-white/40">
                {data.requests.value.toLocaleString()} requests
                {data.requests.failed > 0 && `, ${data.requests.failed.toLocaleString()} failed`}
              </span>
            </Tile>
            <BudgetTile overview={data} />
          </div>
        )}

        {data && !hasUsage && (
          <div className="glass-card p-6 text-sm text-white/60">
            <p className="text-white/85 font-medium mb-1">No usage recorded in this period yet.</p>
            Requests sent through this gateway appear here automatically. To include Claude Code, run{' '}
            <code className="text-glow-cyan/90">ollabridge usage claude-code</code> and add the printed variables to
            your shell.
          </div>
        )}

        {hasUsage && (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <Panel
                className="lg:col-span-2"
                title={metric === 'cost' ? 'API cost per day' : 'Tokens per day'}
                action={
                  <div className="flex gap-2">
                    <Segmented
                      label="Metric"
                      value={metric}
                      onChange={setMetric}
                      options={[
                        { value: 'tokens', label: 'Tokens' },
                        { value: 'cost', label: 'Cost' },
                      ]}
                    />
                    <Segmented
                      label="View"
                      value={view}
                      onChange={setView}
                      options={[
                        { value: 'chart', label: 'Chart' },
                        { value: 'table', label: 'Table' },
                      ]}
                    />
                  </div>
                }
              >
                {series.data && series.data.series.length > 0 ? (
                  <div className="space-y-3">
                    {view === 'chart' ? (
                      <StackedColumns data={series.data} colors={colors} />
                    ) : (
                      <SeriesTable data={series.data} />
                    )}
                    <Legend keys={seriesKeys} colors={colors} />
                  </div>
                ) : (
                  <Empty>{metric === 'cost' ? 'No priced API usage in this period.' : 'Nothing to plot.'}</Empty>
                )}
              </Panel>

              <Panel title={metric === 'cost' ? 'API cost by provider' : 'Tokens by provider'}>
                {share.data && share.data.items.length > 0 ? (
                  <ShareList data={share.data} colors={colors} metric={metric} />
                ) : (
                  <Empty>{metric === 'cost' ? 'No priced API usage in this period.' : 'Nothing to show.'}</Empty>
                )}
              </Panel>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <Panel className="lg:col-span-2" title="Top agents / workflows">
                {agents.data && agents.data.items.length > 0 ? (
                  <table className="w-full text-sm">
                    <thead className="text-xs text-white/45">
                      <tr>
                        <th className="text-left font-medium pb-2">Agent</th>
                        <th className="text-left font-medium pb-2">Main provider</th>
                        <th className="text-right font-medium pb-2">Tokens</th>
                        <th className="text-right font-medium pb-2">API cost</th>
                        <th className="text-right font-medium pb-2">Change</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agents.data.items.map((agent) => (
                        <tr key={`${agent.application_id}/${agent.agent_id}`} className="border-t border-white/5">
                          <td className="py-2.5 pr-3">
                            <div className="text-white/85">{agent.agent_id}</div>
                            <div className="text-xs text-white/40">{agent.application_id}</div>
                          </td>
                          <td className="py-2.5 pr-3 text-white/70">
                            <span className="inline-flex items-center gap-1.5">
                              <span
                                className="w-2 h-2 rounded-[2px]"
                                style={{ background: colors[agent.top_provider] ?? '#6b7280' }}
                              />
                              {agent.top_provider}
                            </span>
                          </td>
                          <td className="py-2.5 text-right tabular-nums text-white/85">{formatTokens(agent.tokens)}</td>
                          <td className="py-2.5 text-right tabular-nums text-white/85">{formatUsd(agent.cost_micro)}</td>
                          <td className="py-2.5 text-right tabular-nums text-white/60">
                            {agent.delta_pct === null ? 'new' : `${agent.delta_pct >= 0 ? '+' : ''}${agent.delta_pct}%`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <Empty>No agents yet.</Empty>
                )}
              </Panel>

              <Panel title="Key insights">
                {insights.data && insights.data.items.length > 0 ? (
                  <ul>
                    {insights.data.items.map((insight) => (
                      <InsightRow key={insight.id} insight={insight} />
                    ))}
                  </ul>
                ) : (
                  <Empty>Nothing stands out in this period.</Empty>
                )}
              </Panel>
            </div>
          </>
        )}

        {sources.data && (
          <Panel title="Data sources">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
              <div className="md:col-span-2">
                {sources.data.sources.length > 0 ? (
                  <ul className="space-y-1.5">
                    {sources.data.sources.map((source) => (
                      <li key={source.source} className="flex justify-between gap-3 text-white/70">
                        <span>{source.source.replaceAll('_', ' ')}</span>
                        <span className="text-white/45">
                          {source.events.toLocaleString()} events · last {new Date(source.last_seen).toLocaleString()}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-white/40">No source has reported yet.</span>
                )}
              </div>
              <div className="text-white/55 space-y-1">
                <p>
                  Cloud sync:{' '}
                  <span className="text-white/80">{sources.data.cloud_sync.enabled ? 'on' : 'off'}</span>
                  {!sources.data.cloud_sync.enabled && ` — ${sources.data.cloud_sync.reason}`}
                </p>
                <p>
                  Price catalog: <span className="text-white/80">{sources.data.pricing_version}</span>
                </p>
              </div>
            </div>
          </Panel>
        )}
      </div>
    </div>
  )
}
