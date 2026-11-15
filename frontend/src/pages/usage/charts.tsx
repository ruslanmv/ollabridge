/** Charts for the Usage page: plain SVG/HTML, no chart library. */

import { useState } from 'react'
import type { UsageBreakdown, UsageTimeseries } from '../../lib/usageApi'
import { formatDay, formatMetric } from './format'

const GRID = 'rgba(255,255,255,0.07)'
const AXIS = 'rgba(255,255,255,0.16)'
const MUTED = '#8b93a7'

/** A "nice" axis maximum and four tick values at or above `max`. */
function niceScale(max: number): { top: number; ticks: number[] } {
  if (max <= 0) return { top: 1, ticks: [0, 1] }
  const rough = max / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? rough
  const top = Math.ceil(max / step) * step
  const ticks: number[] = []
  for (let value = 0; value <= top + step / 2; value += step) ticks.push(value)
  return { top, ticks }
}

export function Legend({ keys, colors }: { keys: string[]; colors: Record<string, string> }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-white/60">
      {keys.map((key) => (
        <li key={key} className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-[3px] shrink-0" style={{ background: colors[key] }} />
          {key}
        </li>
      ))}
    </ul>
  )
}

/** Stacked daily columns, one segment per provider, with a per-day tooltip. */
export function StackedColumns({
  data,
  colors,
}: {
  data: UsageTimeseries
  colors: Record<string, string>
}) {
  const [hover, setHover] = useState<number | null>(null)
  const metric = data.metric === 'cost' ? 'cost' : 'tokens'
  const days = data.days
  const totals = days.map((_, i) => data.series.reduce((sum, s) => sum + s.values[i], 0))
  const { top, ticks } = niceScale(Math.max(...totals, 0))

  const width = 720
  const height = 240
  const pad = { left: 52, right: 8, top: 10, bottom: 24 }
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom
  const band = plotW / Math.max(days.length, 1)
  const barW = Math.max(2, Math.min(24, band - 2))
  const y = (value: number) => pad.top + plotH - (value / top) * plotH
  const labelEvery = Math.max(1, Math.ceil(days.length / 7))

  return (
    <div className="relative" onMouseLeave={() => setHover(null)}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-auto block"
        role="img"
        aria-label={`Daily ${metric} by provider, ${formatDay(days[0])} to ${formatDay(days[days.length - 1])}`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} stroke={tick === 0 ? AXIS : GRID} />
            <text x={pad.left - 8} y={y(tick) + 3.5} textAnchor="end" fontSize="10" fill={MUTED}>
              {formatMetric(metric, tick)}
            </text>
          </g>
        ))}

        {days.map((day, i) => {
          const x = pad.left + i * band + (band - barW) / 2
          let running = 0
          const topIndex = data.series.reduce((last, s, index) => (s.values[i] > 0 ? index : last), -1)
          return (
            <g key={day} opacity={hover === null || hover === i ? 1 : 0.45}>
              {data.series.map((series, index) => {
                const value = series.values[i]
                if (value <= 0) return null
                const yTop = y(running + value)
                const yBottom = y(running)
                running += value
                // 2px surface gap between stacked segments; only the top
                // segment's data-end is rounded.
                const h = Math.max(yBottom - yTop - 2, 1)
                const r = index === topIndex ? Math.min(4, barW / 2, h) : 0
                return (
                  <path
                    key={series.key}
                    fill={colors[series.key]}
                    d={`M${x},${yTop + h} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + barW - r} Q${x + barW},${yTop} ${x + barW},${yTop + r} V${yTop + h} Z`}
                  />
                )
              })}
              {i % labelEvery === 0 && (
                <text x={x + barW / 2} y={height - 7} textAnchor="middle" fontSize="10" fill={MUTED}>
                  {formatDay(day)}
                </text>
              )}
              {/* Hit target: the whole band, far larger than the bar. */}
              <rect
                x={pad.left + i * band}
                y={pad.top}
                width={band}
                height={plotH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
              />
            </g>
          )
        })}
      </svg>

      {hover !== null && (
        <div
          className="absolute top-2 z-10 pointer-events-none rounded-lg border border-white/10 bg-navy-800/95 px-3 py-2 text-xs shadow-xl min-w-[160px]"
          style={
            hover < days.length / 2
              ? { left: `${((pad.left + (hover + 1) * band) / width) * 100}%` }
              : { right: `${((width - pad.left - hover * band) / width) * 100}%` }
          }
        >
          <div className="text-white/90 font-medium mb-1">{formatDay(days[hover])}</div>
          {data.series
            .filter((series) => series.values[hover] > 0)
            .map((series) => (
              <div key={series.key} className="flex items-center gap-2 text-white/70">
                <span className="w-2 h-2 rounded-[2px]" style={{ background: colors[series.key] }} />
                <span className="flex-1">{series.key}</span>
                <span className="tabular-nums text-white/90">{formatMetric(metric, series.values[hover])}</span>
              </div>
            ))}
          <div className="flex justify-between gap-4 mt-1 pt-1 border-t border-white/10 text-white/60">
            <span>Total</span>
            <span className="tabular-nums text-white/90">{formatMetric(metric, totals[hover])}</span>
          </div>
        </div>
      )}
    </div>
  )
}

/** The same series as a table, for readers who want the numbers. */
export function SeriesTable({ data }: { data: UsageTimeseries }) {
  const metric = data.metric === 'cost' ? 'cost' : 'tokens'
  const active = data.days.map((_, i) => i).filter((i) => data.series.some((s) => s.values[i] > 0))
  return (
    <div className="max-h-[240px] overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-navy-800 text-white/50">
          <tr>
            <th className="text-left font-medium py-1.5 pr-3">Day</th>
            {data.series.map((series) => (
              <th key={series.key} className="text-right font-medium py-1.5 px-2">
                {series.key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {active.map((i) => (
            <tr key={data.days[i]} className="border-t border-white/5 text-white/75">
              <td className="py-1.5 pr-3">{formatDay(data.days[i])}</td>
              {data.series.map((series) => (
                <td key={series.key} className="text-right tabular-nums py-1.5 px-2">
                  {formatMetric(metric, series.values[i])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** One row per provider: name, share bar on a common scale, figure. */
export function ShareList({
  data,
  colors,
  metric,
}: {
  data: UsageBreakdown
  colors: Record<string, string>
  metric: 'tokens' | 'cost'
}) {
  const max = Math.max(...data.items.map((item) => item.value), 1)
  return (
    <ul className="space-y-3">
      {data.items.map((item) => (
        <li key={item.key} title={`${item.key}: ${formatMetric(metric, item.value)} (${(item.share * 100).toFixed(1)}%)`}>
          <div className="flex items-baseline justify-between text-xs mb-1">
            <span className="text-white/80">{item.key}</span>
            <span className="tabular-nums text-white/60">
              <span className="text-white/90">{formatMetric(metric, item.value)}</span>
              {'  '}
              {(item.share * 100).toFixed(1)}%
            </span>
          </div>
          <div className="h-2 rounded-full bg-white/[0.06]">
            <div
              className="h-2 rounded-full"
              style={{ width: `${Math.max((item.value / max) * 100, 1)}%`, background: colors[item.key] }}
            />
          </div>
        </li>
      ))}
    </ul>
  )
}
