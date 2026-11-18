# Usage by model — design

**Status:** built 2026-11-18 (uncommitted; live after the gateway restarts) · **Scope:** the Usage page (`frontend/src/pages/usage/`) and
`src/ollabridge/usage/` · **Date:** 2026-11-18

A per-model usage meter for one person watching their own gateway. It upgrades the existing
Usage & Cost page. No other page is changed. It keeps the same navy and cyan look, `glass-card`
panels and `Segmented` controls, and adds no new library.

---

## 1. What exists today (read from the code and the live `usage.db`)

**Per request.** `usage/capture.py` writes one `usage_events` row per served request, from
`_record_trace`. The row carries:

- `provider`, `billing_provider`, `model` (resolved) and `requested_model`
- `execution`, `billing_mode` (`api | subscription | local | free_tier`)
- five disjoint token dimensions: `null` means unknown, never 0
- `measurement`, `status`, `error_category` and `latency_ms`
- `application_id` (from the `X-OllaBridge-App` header, else `x-client-type`) and `agent_id`
- cost in micro-USD: `estimated_micro` and `reported_micro`

The row holds no prompt or answer text. The schema can't carry any.

**Rollups.** `store.rollup_rows()` groups by day, provider, model, app, agent, billing mode,
measurement and status. Model is already a grouping key, so the per-model view needs no new table.

**API.** `/v1/bi/overview | timeseries | breakdown | agents | insights | sources` exist. The page
groups by **provider** only. It never shows models.

**Inventory.** `/v1/models` lists what each healthy runtime or provider serves now, with `id`,
`owned_by`, `source` (`ollama`, `open_webui`, `byok:*`, …) and `category`. If a runtime is unhealthy,
or a provider's list call fails, its models are silently left out.

**The live ledger** (120 events, 2026-11-17 → 18, aggregates only):

| Fact | Consequence for the design |
| --- | --- |
| 84 of 120 requests failed (`provider_bad_request` 75, `provider_timeout` 9). Every failure is filed under `provider=ollama, execution=local_device`, including `openwebui/…` models. | **Bug.** If a provider add-on fails, `trace_provider` stays `None`, and `_classify` maps `None` to local Ollama. The same model then shows up as two rows (ollama and openwebui), and the failures sit on a runtime that never saw them. Fix in §4. |
| `openwebui/internal-kimi-k3` has 75 requests and all 75 failed. It isn't in `/v1/models` any more, because its successor is `…-kimi-k3-1-pro`. | A model can have usage after it was removed. The view has to show it, flagged "not in inventory". |
| OpenWebUI rows are `billing_mode=free_tier`. Local rows are `local`. None have a price. | The cost shows **Free tier**, **Local** or **Unpriced**, never `$0.00`. Today's KPI shows `$0.00`. |
| `application_id` and `agent_id` are `null` on every row. | "Usage by source" would be 100 % Unattributed, so the panel is collapsed to a one-line hint (§3.4). |
| `requested_model == model` on every row. `streamed=0`. No trace has more than one event. | The alias and retry rules below hold. Right now there are no aliases or failovers to merge. |

---

## 2. Layout

```
┌ Usage ─────────────────────────────── [Details] [USD] [7d|30d|90d] ┐
│ ┌Total tokens┐ ┌Estimated cost┐ ┌Models used┐ ┌Failed requests┐     │  KPIs (§3.1)
│ │ 152.2K     │ │ Unpriced     │ │ 6 of 70   │ │ 84 · 70 %     │     │
│ └────────────┘ └──────────────┘ └───────────┘ └───────────────┘     │
│ ┌ Usage over time ───────────── [Tokens|Requests|Cost] ┐ ┌Insights┐ │  §3.3, §3.6
│ │ stacked columns, top 6 models + others               │ │ ⚠ …    │ │
│ └───────────────────────────────────────────────────────┘ └────────┘ │
│ ┌ Models ─────────────────────────── [search……] ┐                    │  core (§3.2)
│ │ Model · Provider  Total  In  Out  Req  Failed  Trend  Cost          │
│ │ ▸ internal-gemma4-31b  openwebui  88.5K … ▁▃▆                       │
│ │ ▸ internal-kimi-k3  ollama?  —  …  75  75 (100 %)  Not in inventory │
│ └──────────────────────────────────────────────┘                    │
│ ┌ Usage by source ┐ ┌ Model inventory ─────────────── Open Models → ┐ │  §3.4, §3.5
│ └─────────────────┘ └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
       Clicking a model row opens the detail panel (§3.2): a right-side
       sheet on desktop, full-screen on mobile.
```

**Show details** keeps today's extras: the budget tile, billed cost, measurement badges and the
data-sources panel. Nothing that exists today is removed. The provider share list is replaced by the
models table, which can be filtered by provider.

On mobile (< 640 px), the KPIs sit two by two. The table drops to Model, Total, Failed and a trend
column, and the rest appears in the detail sheet. There's no horizontal page scroll.

---

## 3. Sections and where each number comes from

All page numbers come from **one new endpoint**, `GET /v1/bi/models?from&to`. It is computed from a
single `rollup_rows()` read, so the KPIs, the table and the chart are sums over the same rows and
reconcile by construction. Budget and forecast keep using `/v1/bi/overview`.

### 3.1 KPIs

| KPI | Value | When it can't be known |
| --- | --- | --- |
| Total tokens | Σ known tokens over all rows | Requests with unknown counts are listed underneath ("84 requests without token counts") and are never added as 0 |
| Estimated cost | Σ `cost_micro` on API and subscription rows that have a price | **Unpriced** if no API tokens are priced. **Not billed** if all usage is local or free tier. "≥ $x · some unpriced" if partly priced |
| Models used | distinct (provider, model) pairs with ≥ 1 request, shown "of N available" | N is left out if the inventory couldn't be read |
| Failed requests | count and % of requests | — |

The delta against the prior period is kept from today's page.

### 3.2 Models table (the core)

**Row key:** `(provider, model)`, where `model` is the *resolved* id.

- The same model reached through two providers or runtimes stays two rows.
- A request sent through an alias is one event, recorded under its resolved model, so it is never
  counted twice. The aliases it was requested as (`requested_model ≠ model`) are listed in the detail
  panel.
- Model ids are shown exactly as served, such as `openwebui/internal-kimi-k3-1-pro`. A model isn't
  given a second name.

**Columns:** Model · Provider/runtime · Total · Input · Output · Requests · Failed · 30-point trend
sparkline · Cost.

- "Input" is `input + cache_read + cache_write`. "Output" is `output + reasoning`. The detail panel
  shows each part separately when it's non-zero.
- Every column sorts. Search is client-side, over the model id and the provider.
- Unknown counts show as "—" with a tooltip, never as 0.

**Row badges** (from data only):

- **Not in inventory** — used in the period, but missing from `/v1/models` now.
- **Estimated** — the counts are approximated from text length.
- **Runtime unreachable** — the provider's inventory call failed (§3.5).

**Detail panel:**

- Daily tokens and requests for this model.
- The input/output split.
- Failures by `error_category`.
- Provider, runtime/source and billing mode.
- The measurement mix, the requested-as aliases, average latency and the last request time.
- A link to the Models page.

### 3.3 One time chart

Tokens, Requests or Cost, over 7, 30 or 90 days, stacked by model: the top 6, plus "others". It
reuses `StackedColumns` from `charts.tsx`. Each model gets a colour from the existing categorical
slots, assigned by name order. The same colour is used for its sparkline, so colour follows the
model, not its rank.

In Cost mode, only priced API rows are plotted. If none exist, the chart says "No priced usage in
this period" rather than drawing a zero line.

### 3.4 Usage by source

The panel groups by `application_id`, and null shows as "Unattributed". It's shown only when at least
one request in the period carries a source.

Otherwise it collapses to one line: *"No request named its source. Send `X-OllaBridge-App: <name>` to
see usage by app."* That is today's live state.

Source names aren't mapped to invented categories such as "assistant" or "workflow". The labels the
callers sent are shown as they are.

### 3.5 Model inventory, kept apart from usage

The panel shows three counts, each with an expandable list and a link to the Models page:

- **Available** — from `/v1/models`, split by source.
- **Used in period**.
- **Never used in period**.

Usage of models outside the inventory is counted as "used, not in inventory". Inventory never adds
rows to the usage table, and usage never adds models to "available".

If a runtime or provider can't be listed, the panel says so by name, for example "Ollama: not
reachable, its models aren't counted". Its usage rows stay, marked **Runtime unreachable**.

### 3.6 Insights (real data only, deterministic)

Each insight carries the numbers it came from and links to the model row.

| Insight | Rule |
| --- | --- |
| Repeated failures | a model with ≥ 3 failures and a fail rate of ≥ 50 % in the period. Its top `error_category` is named |
| Used but not in inventory | the model has requests but isn't in `/v1/models` (often a rename; the new id isn't guessed) |
| Spike | a day's tokens are ≥ 3 × the median of the previous ≥ 5 days that had usage |
| Unpriced usage | API-billed tokens with no price |

The existing `/v1/bi/insights` rules (estimated share, cache hits) stay under Details.

### 3.7 States

| State | Shown as |
| --- | --- |
| Loading | skeleton KPIs and table rows, with no fake numbers |
| Empty period | today's "No usage recorded in this period yet" card. The inventory panel still shows |
| API error | the existing amber error card with the message. Sections that loaded keep their data |
| Runtime unreachable | a note in the inventory panel and a badge on the affected rows (§3.5) |
| Capture off (`USAGE_ENABLED=false`) | "Usage recording is off" with the setting name, instead of an empty page |

---

## 4. Backend changes (minimal)

1. **Attribute failed provider requests correctly** (the bug in §1).
   - `addons/providers/router.py` notes the route being tried *before* each attempt. Today the route
     is noted only after success, so a failure still knows which provider it was on.
   - `usage/capture.py` uses that noted route for a failed request whose trace has no provider.
     Before, an unknown provider on a failure was filed under local Ollama. A request with no route
     still falls back to Ollama as before, because that is the path it then takes.
   - A local Ollama success is unaffected (`trace_provider="ollama-local"`).
2. **Inventory with provenance.** The body of the `/v1/models` handler moves into a helper,
   `collect_models()` (on `app.state.collect_models`). The helper returns the models plus the sources that couldn't be listed.
   - `/v1/models` keeps its exact response.
   - Add-on entries gain one OllaBridge extra field, `provider_id` (the registry id that the ledger
     records as `provider`), so usage and inventory join exactly. Today the inventory says
     `open_webui` where the ledger says `openwebui`.
3. **`store.model_rows()`** is a new read, beside `rollup_rows()`, which is unchanged. It adds the
   requested id, error category, latency and `priced_events`. Together with `unpriced_tokens`,
   `priced_events` tells "Unpriced" apart from a real `$0`.
4. **New local module `usage/model_usage.py`** and the route `GET /v1/bi/models`. `bi_core.py` stays
   untouched, because it's vendored and hash-pinned with OllaBridge Cloud. The response holds:
   - `totals`
   - `models[]`: the key, sums, failures by category, requested-as aliases, a daily series, the cost
     state and inventory flags
   - `daily[]`
   - `sources[]`
   - `inventory`: available, used, never used and unreachable
   - `insights[]`
5. **No schema change** to `usage_events` and no change to the contract.

Already true and pinned by tests:

- One event per request: `event_id` is the idempotency key.
- A stream is recorded once, at its end, not per chunk.
- A failover is recorded once, with its final outcome (`USAGE_INTELLIGENCE.md` §11).

---

## 5. Tests

**Backend** (`tests/test_usage_models.py`, run in the WSL venv):

- The KPI totals equal the table's sum and the chart's sum.
- Unknown tokens aren't counted as 0.
- An API model with no price comes out `unpriced`. Partly priced comes out as a floor. Local and free
  tier come out `not_billed`, never 0.
- The same model through two providers gives two rows. An alias request is counted once, and its
  aliases are listed.
- A removed model with usage is flagged `in_inventory: false`. An inventory model without usage is
  listed as "never used". An unreachable source is reported.
- A failed provider add-on request is attributed to that provider, not to Ollama.
- Each insight fires on its threshold and stays silent below it.

**Frontend.** The repo has no test runner. The derivations (the cost label, the page state
loading / empty / error / unreachable / capture-off, sorting and search) live in a pure
`modelUsage.ts`. They are tested with Node's built-in `node --test` on the tsc output, so no library
is added. Run them with `npm run test:unit` in `frontend/`.

The rendered page was checked in the browser at 1440 px and 375 px. The check used a copy of the live
data directory, served by a throwaway gateway on another port.

---

## 6. Decision: history stays as recorded

The 84 failed rows that were recorded under `ollama` before the fix are shown exactly as stored. So
`ollama · openwebui/internal-kimi-k3` appears beside `openwebui · …`, flagged **Not in inventory**.
The fix in §4.1 applies only to new requests, and `usage.db` is never rewritten.

A failing model that is also gone from the inventory gets one insight ("failed N of N … no longer in
the model list"), not two.
