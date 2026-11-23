// Per-model usage view: page states, cost labels, sorting/search, chart.
// Run with `npm run test:unit` (compiles src/pages/usage/modelUsage.ts first).
const test = require('node:test')
const assert = require('node:assert/strict')
const m = require('./.build/pages/usage/modelUsage.js')

const USD = { code: 'USD', usd_rate: 1, source: 'default' }
const days = ['2026-11-16', '2026-11-17', '2026-11-18']

function model(over = {}) {
  return {
    provider: 'acme',
    model: 'acme/m1',
    source: null,
    source_display_name: null,
    runtime_unreachable: false,
    in_inventory: true,
    tokens: { total: 140, input: 100, output: 40, dimensions: {} },
    requests: 1,
    failed: 0,
    unknown_usage: 0,
    errors: {},
    requested_as: {},
    measurement: {},
    execution: [],
    billing_providers: [],
    cost: { state: 'unpriced', micro: null, unpriced_tokens: 140, modes: ['api'] },
    avg_latency_ms: null,
    last_seen: null,
    daily: { tokens: [0, 0, 140], requests: [0, 0, 1], cost: [0, 0, 0] },
    ...over,
  }
}

function view(models, over = {}) {
  const sum = (k) => days.map((_, i) => models.reduce((s, x) => s + x.daily[k][i], 0))
  return {
    period: { from: days[0], to: days[2] },
    capture_enabled: true,
    days,
    totals: { tokens: { total: 0, input: 0, output: 0 }, requests: models.reduce((s, x) => s + x.requests, 0), failed: 0, failed_pct: null, unknown_usage: 0, models_used: models.length, cost: { state: 'none', micro: null, unpriced_tokens: 0, modes: [] } },
    daily: { tokens: sum('tokens'), requests: sum('requests'), cost: sum('cost') },
    models,
    sources: { attributed: false, items: [] },
    inventory: { available: null, used: 0, never_used: null, not_in_inventory: null, unreachable: [], by_source: {}, never_used_models: [] },
    insights: [],
    ...over,
  }
}

test('page states: loading, error, empty, capture off, ready', () => {
  assert.equal(m.pageState({ isLoading: true, isError: false }), 'loading')
  assert.equal(m.pageState({ isLoading: false, isError: true }), 'error')
  assert.equal(m.pageState({ isLoading: false, isError: false, data: view([]) }), 'empty')
  assert.equal(m.pageState({ isLoading: false, isError: false, data: view([], { capture_enabled: false }) }), 'capture_off')
  assert.equal(m.pageState({ isLoading: false, isError: false, data: view([model()]) }), 'ready')
  // Data already loaded wins over a failed background refresh.
  assert.equal(m.pageState({ isLoading: false, isError: true, data: view([model()]) }), 'ready')
})

test('missing pricing is shown as Unpriced, never $0.00', () => {
  const label = m.costLabel({ state: 'unpriced', micro: null, unpriced_tokens: 5, modes: ['api'] }, USD)
  assert.equal(label.text, 'Unpriced')
  assert.doesNotMatch(label.text, /0\.00/)
  assert.equal(m.costLabel({ state: 'not_billed', micro: null, unpriced_tokens: 0, modes: ['local'] }, USD).text, 'Local')
  assert.equal(m.costLabel({ state: 'not_billed', micro: null, unpriced_tokens: 0, modes: ['free_tier'] }, USD).text, 'Free tier')
  assert.equal(m.costLabel({ state: 'not_billed', micro: null, unpriced_tokens: 0, modes: ['free_tier', 'local'] }, USD).text, 'Not billed')
  assert.equal(m.costLabel({ state: 'none', micro: null, unpriced_tokens: 0, modes: [] }, USD).text, '—')
  assert.match(m.costLabel({ state: 'partial', micro: 2_500_000, unpriced_tokens: 9, modes: ['api'] }, USD).text, /^≥ /)
  assert.match(m.costLabel({ state: 'priced', micro: 2_500_000, unpriced_tokens: 0, modes: ['api'] }, USD).text, /2\.50/)
})

test('unknown tokens show as a dash, not zero', () => {
  assert.equal(m.tokensLabel(null), '—')
  assert.equal(m.tokensLabel(0), '0')
  assert.equal(m.percent(1, 0), '—')
})

test('sorting keeps unknowns last in both directions; search matches id and provider', () => {
  const a = model({ model: 'a', tokens: { total: 5, input: 5, output: 0, dimensions: {} } })
  const b = model({ model: 'b', tokens: { total: null, input: null, output: null, dimensions: {} } })
  const c = model({ model: 'c', provider: 'other', tokens: { total: 9, input: 9, output: 0, dimensions: {} } })
  assert.deepEqual(m.sortModels([a, b, c], 'total', 'desc').map((x) => x.model), ['c', 'a', 'b'])
  assert.deepEqual(m.sortModels([a, b, c], 'total', 'asc').map((x) => x.model), ['a', 'c', 'b'])
  assert.deepEqual(m.sortModels([c, a, b], 'model', 'asc').map((x) => x.model), ['a', 'b', 'c'])
  assert.deepEqual(m.filterModels([a, b, c], 'OTHER').map((x) => x.model), ['c'])
  assert.deepEqual(m.filterModels([a, b, c], '  ').length, 3)
})

test('the same id through two providers gets two labels; one provider keeps the bare id', () => {
  const labels = m.displayLabels([model({ provider: 'p1', model: 'x' }), model({ provider: 'p2', model: 'x' }), model({ model: 'y' })])
  assert.deepEqual(Object.values(labels).sort(), ['x · p1', 'x · p2', 'y'])
})

test('chart stacks reconcile with the daily totals, with an others bucket', () => {
  const models = Array.from({ length: 8 }, (_, i) =>
    model({ model: `m${i}`, daily: { tokens: [i, 1, 2], requests: [1, 0, 1], cost: [0, 0, 0] } }),
  )
  const v = view(models)
  const chart = m.chartSeries(v, 'tokens')
  assert.equal(chart.series.length, 7)
  assert.equal(chart.series.at(-1).key, 'others')
  days.forEach((_, i) => assert.equal(chart.series.reduce((s, x) => s + x.values[i], 0), v.daily.tokens[i]))
  assert.equal(m.chartSeries(v, 'cost').series.length, 0) // nothing priced: no zero line
  assert.equal(m.chartSeries(v, 'requests').metric, 'events')
})

test('insight text uses the served ids and the recorded numbers', () => {
  const t = m.insightText({ id: 'x', kind: 'repeated_failures', severity: 'warning', provider: 'acme', model: 'acme/m1', evidence: { failed: 3, requests: 4, top_error: 'provider_bad_request' } })
  assert.equal(t.title, 'acme/m1 failed 3 of 4 requests')
  assert.match(t.detail, /provider bad request/)
})
