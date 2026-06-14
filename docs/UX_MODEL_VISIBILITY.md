# Model Visibility & the Model Selector

This page defines **what models a client sees** in `GET /v1/models` and the
dashboard/selector, and why. It fixes the confusion where a personal user
who shares 5 local models saw 20+ entries — their models mixed with route
aliases and the cloud's own internal catalog, all unlabelled.

## The three concepts users were conflating

A flat selector showed all of these as if they were the same thing:

| Concept | Example | What it really is |
|---|---|---|
| **Shared model** | `granite3.2:latest` | A concrete model on *your* paired device |
| **Route alias** | `ollabridge:auto`, `free-best` | A *policy* that resolves to some model at call time |
| **Cloud catalog** | the Space's own Ollama models | OllaBridge Cloud's built-in fallback models |
| **Enterprise catalog** | `gpt-best`, `claude-best` | Org-provided provider routes (enterprise plans) |

The fix: **label every entry with its origin, and scope what each plan sees.**

## The contract (`GET /v1/models`)

Every entry carries an `x_source` field:

| `x_source` | Meaning | Selector section |
|---|---|---|
| `shared_device` | A model on the caller's own paired device(s) | **My Shared Models** |
| `route_alias` | A smart route / intent alias | **Smart Routes** |
| `cloud_catalog` | The cloud's built-in Ollama fallback models | **Cloud Catalog** |
| `homepilot` | A HomePilot persona | **Personas** |

### Visibility by plan

| Plan | Sees by default | Hidden unless requested |
|---|---|---|
| **Personal** (no org, or `plan=personal`) | shared_device, then route_alias | cloud_catalog, homepilot — request with `?include=catalog` |
| **Enterprise** (`plan=enterprise`) | everything, labelled | — |
| **System** (admin `ob_*` key, anonymous) | everything, labelled (back-compat) | — |

**Ordering matters:** a personal user's *own* shared models come **first**,
because that is the thing they expect to see — it should match the "Model
Inventory: 5 models" count on their device exactly.

### Why personal users don't see the cloud catalog

A single user who paired one device and shared `granite3.2`, `llama3`,
`gemma:2b` wants to pick from *those*. The cloud's own `qwen2.5:0.5b` fallback
and the seeded provider aliases are infrastructure, not "their" models.
Showing them made the dashboard count (5) disagree with the selector (20+).
Enterprise admins, who manage that infrastructure, still see everything.

## How clients should render the selector

Group by `x_source`, show origin on every row, hide empty/disabled sections:

```text
Select a model

MY SHARED MODELS (5)
─────────────────────────────
granite3.2:latest      Shared from your device
llama3:latest          Shared from your device
llama3.1:latest        Shared from your device
codellama:latest       Shared from your device
gemma:2b               Shared from your device

SMART ROUTES (4)
─────────────────────────────
ollabridge:auto        Route • best available
free-best              Route • cheapest free
free-fast              Route • lowest latency
cheap-reasoning        Route • cheap reasoning

CLOUD CATALOG  (hidden)
─────────────────────────────
[ Enable cloud models ]   → re-requests with ?include=catalog
```

For a `homepilot`/persona client like yourfriend.online, the default
(personal) response is exactly the five shared models plus the routes —
nothing else — so the selector matches what the user shared.

## Server behaviour summary (implemented in `ollabridge-cloud`)

`api/ollama_proxy.py::list_models_openai`:

1. Resolve caller `user_id` and look up their org `plan`.
2. Always add the caller's **shared device models first** (`shared_device`).
3. Add **route aliases** (`route_alias`).
4. Add the **cloud catalog** (`cloud_catalog`, `homepilot`) **only** when
   the plan is enterprise/system, or `?include=catalog`/`?include=all`.
5. Every entry is labelled; the list is never an unlabelled union.

## Client checklist

- [ ] Group the selector by `x_source`; never render aliases as if they were models.
- [ ] Show origin text on each row.
- [ ] Default personal users to **My Shared Models** + **Smart Routes**.
- [ ] Offer an explicit "Enable cloud catalog" toggle → `?include=catalog`.
- [ ] Make the dashboard "N models" count equal the `shared_device` count.
