/**
 * Usage & Cost — tokens, spend and attribution for everything this gateway
 * served, plus Claude Code telemetry. Reads /v1/bi/* (usage/routes.py).
 *
 * Every figure says how it was measured (verified / observed / estimated), and
 * subscription usage is shown as an API-equivalent, never as spend.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  Bot,
  Boxes,
  Coins,
  Lightbulb,
  Receipt,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  Wallet,
} from 'lucide-react'
import type { Page } from '../../App'
import {
  usageApi,
  type CostState,
  type DisplayCurrency,
  type Kpi,
  type MeasurementMix,
  type UsageInsight,
} from '../../lib/usageApi'
import { Legend, SeriesTable, StackedColumns } from './charts'
import { USD, assignColors, formatMoney, formatTokens } from './format'
import { ModelDetail } from './ModelDetail'
import { InventoryPanel, ModelInsights, SourcesPanel } from './ModelPanels'
import { ModelTable } from './ModelTable'
import {
  chartSeries,
  costLabel,
  displayLabels,
  modelKey,
  pageState,
  percent,
  tokensLabel,
  type ChartMetric,
} from './modelUsage'

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

function useUsage(days: number) {
  const options = { refetchInterval: 30_000, retry: false } as const
  return {
    models: useQuery({ queryKey: ['usage', 'models', days], queryFn: () => usageApi.models(days), ...options }),
    overview: useQuery({ queryKey: ['usage', 'overview', days], queryFn: () => usageApi.overview(days), ...options }),
    agents: useQuery({ queryKey: ['usage', 'agents', days], queryFn: () => usageApi.agents(days), ...options }),
    insights: useQuery({ queryKey: ['usage', 'insights', days], queryFn: () => usageApi.insights(days), ...options }),
    sources: useQuery({ queryKey: ['usage', 'sources'], queryFn: usageApi.sources, ...options }),
    currency: useQuery({ queryKey: ['usage', 'currency'], queryFn: usageApi.currency, retry: false }),
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
      <div className="text-xl sm:text-2xl font-semibold text-white/95 tabular-nums break-words leading-tight">{value}</div>
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
    <section className={`glass-card p-4 sm:p-5 min-w-0 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-sm font-semibold text-white/90 whitespace-nowrap">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-white/40 py-6 text-center">{children}</p>
}

function BudgetTile({
  overview,
  currency,
}: {
  overview: NonNullable<ReturnType<typeof useUsage>['overview']['data']>
  currency: DisplayCurrency
}) {
  const client = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const save = useMutation({
    // Entered in the display currency; stored in USD like the rest of the ledger.
    mutationFn: (amount: number) =>
      usageApi.setBudget(amount > 0 ? Math.round((amount / currency.usd_rate) * 1_000_000) : null),
    onSuccess: () => {
      setEditing(false)
      client.invalidateQueries({ queryKey: ['usage', 'overview'] })
    },
  })
  const budget = overview.budget

  if (editing) {
    return (
      <Tile icon={Wallet} label={`Monthly budget (${currency.code})`} value="">
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
    <Tile icon={Wallet} label="Budget remaining" value={budget ? formatMoney(budget.remaining_micro, currency) : '—'}>
      {budget ? (
        <>
          <div className="h-1.5 rounded-full bg-white/[0.06]" title={`${budget.remaining_pct}% of the monthly budget left`}>
            <div
              className={`h-1.5 rounded-full ${budget.remaining_micro < 0 ? 'bg-red-400' : 'bg-[#3987e5]'}`}
              style={{ width: `${Math.min(Math.max(100 - budget.remaining_pct, 0), 100)}%` }}
            />
          </div>
          <span className="text-xs text-white/45">
            {formatMoney(budget.spent_micro, currency)} of {formatMoney(budget.limit_micro, currency)} this month
            {budget.projected_overrun && <span className="text-amber-400"> · on course to exceed</span>}
          </span>
        </>
      ) : (
        <span className="text-xs text-white/40">No monthly budget set</span>
      )}
      <button
        onClick={() => {
          setDraft(budget ? ((budget.limit_micro / 1_000_000) * currency.usd_rate).toFixed(2) : '')
          setEditing(true)
        }}
        className="self-start text-xs text-glow-cyan/80 hover:text-glow-cyan"
      >
        {budget ? 'Change' : 'Set budget'}
      </button>
    </Tile>
  )
}

function InsightRow({ insight, currency }: { insight: UsageInsight; currency: DisplayCurrency }) {
  const warning = insight.severity === 'warning'
  const Icon = warning ? TriangleAlert : Lightbulb
  return (
    <li className="flex gap-3 py-3 border-t border-white/5 first:border-t-0 first:pt-0">
      <Icon size={16} className={`mt-0.5 shrink-0 ${warning ? 'text-amber-400' : 'text-glow-cyan/80'}`} />
      <div className="min-w-0">
        <p className="text-sm text-white/85">{insight.title}</p>
        <p className="text-xs text-white/50 mt-0.5">{insight.detail}</p>
        {insight.estimated_saving_micro ? (
          <p className="text-xs text-white/60 mt-0.5">Spent on these: {formatMoney(insight.estimated_saving_micro, currency)}</p>
        ) : null}
      </div>
    </li>
  )
}

const DETAILS_KEY = 'ollabridge_usage_details'

const CURRENCIES = ['USD', 'EUR', 'GBP', 'CHF', 'SEK', 'NOK', 'DKK', 'PLN', 'CZK']

/** Pick the currency costs are shown in. Providers charge in USD, so a rate is
 * always the user's own explicit choice — nothing is fetched or assumed. */
function CurrencyControl({ currency }: { currency: DisplayCurrency }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState(currency.code)
  const [rate, setRate] = useState('')
  const save = useMutation({
    mutationFn: () => usageApi.setCurrency(code, code === 'USD' ? null : Number(rate)),
    onSuccess: () => {
      setOpen(false)
      client.invalidateQueries({ queryKey: ['usage', 'currency'] })
    },
  })
  const rateOk = code === 'USD' || Number(rate) > 0

  if (!open) {
    return (
      <button
        onClick={() => {
          setCode(currency.code)
          setRate(currency.code === 'USD' ? '' : String(currency.usd_rate))
          setOpen(true)
        }}
        title="Providers charge in USD. Other currencies are converted for display at the rate you set."
        className="px-3 py-1.5 rounded-lg border border-white/10 bg-white/[0.03] text-xs text-white/60 hover:text-white/85"
      >
        {currency.code === 'USD'
          ? 'USD'
          : `${currency.code} · 1 USD = ${currency.usd_rate} ${currency.code}`}
      </button>
    )
  }

  return (
    <form
      className="flex items-center gap-2 text-xs"
      onSubmit={(event) => {
        event.preventDefault()
        if (rateOk) save.mutate()
      }}
    >
      <select
        value={code}
        onChange={(event) => setCode(event.target.value)}
        aria-label="Display currency"
        className="rounded-md bg-navy-800 border border-white/10 px-2 py-1.5 text-white/85 outline-none"
      >
        {CURRENCIES.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      {code !== 'USD' && (
        <label className="flex items-center gap-1.5 text-white/55">
          1 USD =
          <input
            autoFocus
            type="number"
            min="0"
            step="0.0001"
            value={rate}
            onChange={(event) => setRate(event.target.value)}
            placeholder="rate"
            aria-label={`${code} per 1 USD`}
            className="w-20 rounded-md bg-white/5 border border-white/10 px-2 py-1.5 text-white/90 outline-none focus:border-glow-cyan/50"
          />
          {code}
        </label>
      )}
      <button
        type="submit"
        disabled={!rateOk || save.isPending}
        className="px-2.5 py-1.5 rounded-md bg-glow-cyan/15 text-glow-cyan disabled:opacity-40"
      >
        Save
      </button>
      <button type="button" onClick={() => setOpen(false)} className="px-1.5 py-1.5 text-white/45 hover:text-white/75">
        Cancel
      </button>
      {save.isError && <span className="text-amber-400">{(save.error as Error).message}</span>}
    </form>
  )
}

/** Estimated cost: a figure only where prices exist ("Unpriced", "Local",
 * "Free tier" otherwise — never a made-up $0.00). */
function CostTile({ cost, currency }: { cost: CostState; currency: DisplayCurrency }) {
  const label = costLabel(cost, currency)
  return (
    <Tile icon={Coins} label="Estimated cost" value={label.text}>
      <span className={`text-xs ${cost.state === 'partial' || cost.state === 'unpriced' ? 'text-amber-400/90' : 'text-white/40'}`}>
        {cost.state === 'priced'
          ? 'API usage at catalog or provider prices'
          : cost.state === 'subscription'
            ? 'API equivalent; covered by a subscription'
            : cost.state === 'none'
              ? 'Nothing measured'
              : label.hint}
      </span>
    </Tile>
  )
}

function SkeletonTile() {
  return (
    <div className="glass-card-sm p-4 flex flex-col gap-2 min-w-0" aria-hidden="true">
      <div className="h-3 w-20 rounded bg-white/[0.06] animate-pulse" />
      <div className="h-7 w-28 rounded bg-white/[0.08] animate-pulse" />
      <div className="h-3 w-24 rounded bg-white/[0.05] animate-pulse" />
    </div>
  )
}

function SkeletonRows() {
  return (
    <div className="space-y-2" aria-hidden="true">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-9 rounded bg-white/[0.04] animate-pulse" />
      ))}
    </div>
  )
}

const METRICS: { value: ChartMetric; label: string }[] = [
  { value: 'tokens', label: 'Tokens' },
  { value: 'requests', label: 'Requests' },
  { value: 'cost', label: 'Cost' },
]

const CHART_TITLE: Record<ChartMetric, string> = {
  tokens: 'Tokens per day',
  requests: 'Requests per day',
  cost: 'Cost per day',
}

export function UsagePage({ onNavigate }: { onNavigate?: (page: Page) => void }) {
  const [days, setDays] = useState(30)
  const [metric, setMetric] = useState<ChartMetric>('tokens')
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const [selected, setSelected] = useState<string | null>(null)
  // "Details" adds the budget, billed cost and agents tiles, data-quality
  // badges, the agents table, the older insights and the data sources.
  const [detailed, setDetailedState] = useState(() => {
    try {
      return localStorage.getItem(DETAILS_KEY) === 'true'
    } catch {
      return false
    }
  })
  const setDetailed = (value: boolean) => {
    setDetailedState(value)
    try {
      localStorage.setItem(DETAILS_KEY, String(value))
    } catch {
      // storage unavailable: the choice just does not persist
    }
  }
  const { models, overview, agents, insights, sources, currency: currencyQuery } = useUsage(days)
  const currency = currencyQuery.data ?? USD
  const openModels = () => onNavigate?.('models')

  const data = models.data
  const state = pageState(models)
  const labels = useMemo(() => displayLabels(data?.models ?? []), [data])
  const chart = useMemo(() => (data ? chartSeries(data, metric) : null), [data, metric])
  // Colours follow the model (stable by name), never its rank, and are
  // shared by the chart, the table and the detail panel.
  const colors = useMemo(
    () => assignColors(data ? chartSeries(data, 'tokens').series.map((s) => s.key) : []),
    [data],
  )
  const selectedModel = data?.models.find((m) => modelKey(m) === selected) ?? null
  const totals = data?.totals
  const over = overview.data

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6">
      <div className="max-w-[1280px] mx-auto space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-white/50">
            Tokens by model, from this gateway’s own records. Only numbers are stored — never your prompts or answers.
          </p>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <button
              onClick={() => setDetailed(!detailed)}
              aria-pressed={detailed}
              className="px-3 py-1.5 rounded-lg border border-white/10 bg-white/[0.03] text-xs text-white/60 hover:text-white/85"
            >
              {detailed ? 'Hide details' : 'Show details'}
            </button>
            <CurrencyControl currency={currency} />
            <Segmented
              label="Period"
              value={days}
              onChange={setDays}
              options={RANGES.map((r) => ({ value: r.days, label: r.label }))}
            />
          </div>
        </div>

        {state === 'error' && (
          <div className="glass-card-sm p-4 text-sm text-amber-300/90" role="alert">
            Could not load usage: {(models.error as Error).message}
          </div>
        )}

        {state === 'capture_off' && (
          <div className="glass-card p-6 text-sm text-white/60">
            <p className="text-white/85 font-medium mb-1">Usage recording is off.</p>
            Set <code className="text-glow-cyan/90">USAGE_ENABLED=true</code> and restart the gateway to start recording
            token usage.
          </div>
        )}

        {state === 'loading' && (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {[0, 1, 2, 3].map((i) => (
                <SkeletonTile key={i} />
              ))}
            </div>
            <Panel title="Models">
              <SkeletonRows />
            </Panel>
          </>
        )}

        {data && totals && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <Tile icon={Activity} label="Total tokens" value={tokensLabel(totals.tokens.total)}>
              {over && <Delta kpi={over.total_tokens} />}
              {totals.tokens.total !== null && (
                <span className="text-xs text-white/40">
                  in {tokensLabel(totals.tokens.input)} · out {tokensLabel(totals.tokens.output)}
                </span>
              )}
              {totals.unknown_usage > 0 && (
                <span className="text-xs text-white/40" title="Requests with no token count are not added as zero">
                  {totals.unknown_usage.toLocaleString()} requests without counts
                </span>
              )}
              {detailed && over && <MixBadges mix={over.total_tokens.measurement_mix} />}
            </Tile>
            <CostTile cost={totals.cost} currency={currency} />
            <Tile
              icon={Boxes}
              label="Models used"
              value={totals.models_used.toLocaleString()}
            >
              <span className="text-xs text-white/40">
                {data.inventory.available === null
                  ? 'Model list unavailable'
                  : `of ${data.inventory.available.toLocaleString()} available`}
              </span>
            </Tile>
            <Tile icon={TriangleAlert} label="Failed requests" value={totals.failed.toLocaleString()}>
              <span className={`text-xs ${totals.failed ? 'text-amber-300/90' : 'text-white/40'}`}>
                {totals.requests ? `${percent(totals.failed, totals.requests)} of ${totals.requests.toLocaleString()} requests` : 'No requests'}
              </span>
            </Tile>
          </div>
        )}

        {detailed && over && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Tile icon={Receipt} label="Billed cost" value={formatMoney(over.billed_cost_micro.value, currency)}>
              <Delta kpi={over.billed_cost_micro} invert />
              <span className="text-xs text-white/40">Charges stated by providers</span>
            </Tile>
            <Tile icon={Bot} label="Active agents" value={String(over.active_agents.value)}>
              <span className="text-xs text-white/45">
                {over.active_agents.delta >= 0 ? '+' : ''}
                {over.active_agents.delta} vs prior period
              </span>
            </Tile>
            <BudgetTile overview={over} currency={currency} />
          </div>
        )}

        {state === 'empty' && (
          <div className="glass-card p-6 text-sm text-white/60">
            <p className="text-white/85 font-medium mb-1">No usage recorded in this period yet.</p>
            Requests sent through this gateway appear here automatically. To include Claude Code, run{' '}
            <code className="text-glow-cyan/90">ollabridge usage claude-code</code> and add the printed variables to
            your shell.
          </div>
        )}

        {state === 'ready' && data && chart && (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 lg:items-start">
              <Panel
                className="lg:col-span-2"
                title={CHART_TITLE[metric]}
                action={
                  <div className="flex flex-wrap gap-2 justify-end">
                    <Segmented label="Metric" value={metric} onChange={setMetric} options={METRICS} />
                    {detailed && (
                      <Segmented
                        label="View"
                        value={view}
                        onChange={setView}
                        options={[
                          { value: 'chart', label: 'Chart' },
                          { value: 'table', label: 'Table' },
                        ]}
                      />
                    )}
                  </div>
                }
              >
                {chart.series.length > 0 ? (
                  <div className="space-y-3">
                    {view === 'chart' || !detailed ? (
                      <StackedColumns data={chart} colors={colors} currency={currency} />
                    ) : (
                      <SeriesTable data={chart} currency={currency} />
                    )}
                    <Legend keys={chart.series.map((s) => s.key)} colors={colors} />
                  </div>
                ) : (
                  <Empty>{metric === 'cost' ? 'No priced usage in this period.' : 'Nothing to plot.'}</Empty>
                )}
              </Panel>

              <Panel title="Insights">
                <ModelInsights
                  insights={data.insights}
                  onSelect={(provider, model) => setSelected(modelKey({ provider, model }))}
                />
              </Panel>
            </div>

            <Panel title="Models" action={<span className="text-xs text-white/40">{data.models.length} in this period</span>}>
              <ModelTable
                models={data.models}
                colors={colors}
                labels={labels}
                currency={currency}
                selected={selected}
                onSelect={setSelected}
              />
            </Panel>
          </>
        )}

        {data && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Panel title="Usage by source">
              <SourcesPanel sources={data.sources} />
            </Panel>
            <Panel className="lg:col-span-2" title="Model inventory">
              <InventoryPanel inventory={data.inventory} onOpenModels={openModels} />
            </Panel>
          </div>
        )}

        {detailed && state === 'ready' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Panel className="lg:col-span-2" title="Top agents / workflows">
              {agents.data && agents.data.items.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-xs text-white/45">
                      <tr>
                        <th className="text-left font-medium pb-2">Agent</th>
                        <th className="text-left font-medium pb-2">Main provider</th>
                        <th className="text-right font-medium pb-2">Tokens</th>
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
                          <td className="py-2.5 pr-3 text-white/70">{agent.top_provider}</td>
                          <td className="py-2.5 text-right tabular-nums text-white/85">{formatTokens(agent.tokens)}</td>
                          <td className="py-2.5 text-right tabular-nums text-white/60">
                            {agent.delta_pct === null ? 'new' : `${agent.delta_pct >= 0 ? '+' : ''}${agent.delta_pct}%`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty>No agents yet.</Empty>
              )}
            </Panel>

            <Panel title="More observations">
              {insights.data && insights.data.items.length > 0 ? (
                <ul>
                  {insights.data.items.map((insight) => (
                    <InsightRow key={insight.id} insight={insight} currency={currency} />
                  ))}
                </ul>
              ) : (
                <Empty>Nothing else stands out.</Empty>
              )}
            </Panel>
          </div>
        )}

        {detailed && sources.data && (
          <Panel title="Data sources">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
              <div className="md:col-span-2">
                {sources.data.sources.length > 0 ? (
                  <ul className="space-y-1.5">
                    {sources.data.sources.map((source) => (
                      <li key={source.source} className="flex flex-wrap justify-between gap-x-3 text-white/70">
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

      {selectedModel && data && (
        <ModelDetail
          model={selectedModel}
          view={data}
          color={colors[labels[modelKey(selectedModel)]] ?? '#00e5ff'}
          currency={currency}
          onClose={() => setSelected(null)}
          onOpenModels={openModels}
        />
      )}
    </div>
  )
}
