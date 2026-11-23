// Models -> Testing: model list, selection, summary, queue.
// Run with `npm run test:unit`.
const test = require('node:test')
const assert = require('node:assert/strict')
const t = require('./.build/pages/models/modelTesting.js')

const models = [
  { id: 'ow/kimi', object: 'model', source: 'open_webui', source_display_name: 'Example Chat', category: 'chat' },
  { id: 'ow/persona', object: 'model', source: 'open_webui', source_display_name: 'Example Chat', category: 'preset_or_workflow' },
  { id: 'llama3', object: 'model', source: 'ollama', source_display_name: 'Ollama' },
]
const r = (verdict, reason_code = 'ok') => ({ model: 'm', source: null, verdict, reason_code, plain: '', latency_ms: 1, http_status: 200, detail: null, checked_at: 't' })

test('presets are opt-in; models without a category are checked', () => {
  assert.deepEqual(t.checkable(models, false).map((m) => m.id), ['ow/kimi', 'llama3'])
  assert.equal(t.checkable(models, true).length, 3)
  assert.equal(t.presetCount(models), 1)
})

test('search and source filter', () => {
  assert.deepEqual(t.searchModels(models, 'KIMI', '').map((m) => m.id), ['ow/kimi'])
  assert.deepEqual(t.searchModels(models, '', 'Ollama').map((m) => m.id), ['llama3'])
})

test('select-all toggles only the visible rows', () => {
  const on = t.toggleAll(new Set(['other']), ['a', 'b'])
  assert.deepEqual([...on].sort(), ['a', 'b', 'other'])
  const off = t.toggleAll(on, ['a', 'b'])
  assert.deepEqual([...off], ['other'])
})

test('summary counts add up and name a shared cause only above half', () => {
  const s = t.summarize([r('working'), r('slow', 'slow'), r('not_working', 'rate_limited')])
  assert.deepEqual([s.working, s.slow, s.notWorking, s.checked], [1, 1, 1, 3])
  assert.equal(s.sharedCause, null)
  const timeouts = t.summarize([r('not_working', 'check_timeout'), r('not_working', 'provider_timeout'), r('working')])
  assert.match(timeouts.sharedCause, /timed out at the same time/)
  // Retired models failing is about the models, not the provider.
  assert.equal(t.summarize([r('not_working', 'provider_bad_request'), r('not_working', 'model_not_found'), r('working')]).sharedCause, null)
  // Exactly half is not "most".
  assert.equal(t.summarize([r('not_working', 'check_timeout'), r('working')]).sharedCause, null)
})

test('the queue runs at most two at once, in order, and Stop starts nothing new', async () => {
  let active = 0
  let peak = 0
  const order = []
  const worker = async (id) => {
    active++
    peak = Math.max(peak, active)
    order.push(id)
    await new Promise((res) => setTimeout(res, 5))
    active--
  }
  await t.runQueue(['a', 'b', 'c', 'd', 'e'], worker)
  assert.equal(peak, 2)
  assert.deepEqual(order, ['a', 'b', 'c', 'd', 'e'])

  const signal = { aborted: false }
  const started = []
  await t.runQueue(['a', 'b', 'c', 'd'], async (id) => {
    started.push(id)
    signal.aborted = true
    await new Promise((res) => setTimeout(res, 1))
  }, 2, signal)
  assert.ok(started.length <= 2)
})

test('seconds shows a dash for unknown', () => {
  assert.equal(t.seconds(null), '—')
  assert.equal(t.seconds(1100), '1.1 s')
})
