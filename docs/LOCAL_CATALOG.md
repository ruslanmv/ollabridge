# Local Model Catalog

The local-side counterpart to the cloud's [Hugging Face inference catalog](../../../ollabridge-cloud/docs/HUGGINGFACE_CATALOG.md).
Same architecture (schemas → client → parser → scoring → repository → sync →
health → routes), but the discovery source is a local runtime
(`/api/tags` on Ollama today) instead of the Hugging Face Hub.

The goal is one unified model catalog in Admin: cloud providers ship
`<provider>:<model>:<sub-provider>` rows from the HF catalog, local nodes
ship `<node>:<model>` rows from this catalog — both feeding the same
unified table in cloud Admin.

## TL;DR

- **Per-node catalog**, persisted under `~/.ollabridge/local_models.yaml`.
- **Top 3 auto-enabled** by score (configurable via `OBRIDGE_LOCAL_AUTO_ENABLE`).
- **Pull, test, pin, manual-add** all supported via `/local/models/*` REST.
- **Cloud-ready manifest** at `/local/cloud/manifest` — the bridge ships
  this in its heartbeat so cloud Admin can render the local fleet beside
  cloud providers.
- **Background scheduler** every 60 s while the runtime is reachable.
- **YAML persistence**, hand-editable; concurrency guarded by an
  asyncio.Lock; atomic file writes.

## Module layout

```
addons/local_catalog/
├─ schemas.py         LocalModel / LocalModelRow / LocalSyncResult /
│                     ModelCapabilities / PullProgress
├─ client.py          LocalRuntimeClient — wraps Ollama HTTP API
├─ parser.py          /api/tags + /api/show → LocalModelRow (family,
│                     parameter_count, quantization, capabilities)
├─ scoring.py         health(0.30) + latency(0.25) + size(0.15) +
│                     capability(0.15) + recency(0.10) + pin(0.05)
├─ repository.py      YAML-backed, multi-node, asyncio.Lock-guarded
├─ sync_service.py    orchestrator + managed alias writer
├─ health.py          1-token chat probe, bounded concurrency
├─ pulls.py           background `ollama pull` with progress tracking
├─ scheduler.py       periodic refresh (env-driven cadence)
├─ routes.py          /local/* REST
└─ __main__.py        CLI: sync / stats / show / pull / test
```

## Scoring

| Component   | Default | Privacy |
|-------------|---------|---------|
| health      | 0.30    | 0.30    |
| latency     | 0.25    | 0.20    |
| size        | 0.15    | 0.30    |
| capability  | 0.15    | 0.10    |
| recency     | 0.10    | 0.00    |
| pin         | 0.05    | 0.10    |

- **health** — `verified` > `auto` > `broken/removed`.
- **latency** — observed `/api/chat` round-trip on a 1-token probe (EWMA).
- **size** — sweet-spot is 4B–12B on consumer GPUs; tiny is penalised
  (too weak), huge is penalised (too slow).
- **capability** — chat (1.0) + tools (0.5) + vision (0.3) + structured
  (0.2). Embedding-only models collapse to 0.1.
- **recency** — newly-pulled models score higher (90-day half-life).
- **pin** — admin pin always adds the full weight.

Deterministic ties (sorted by `router_model_id`) make repeated runs
produce the same top-N → stable alias regeneration.

## Setup status

```
       sync                  test ok                test fail
AUTO ────────► VERIFIED ──────────────────────────► BROKEN
   ▲                                                  │
   │ admin re-enables                                 │ test ok
   │                                                  ▼
DISABLED ◄────── set_enabled(False)               AUTO/VERIFIED
   ▲
   │ admin disables
   │
   │ 2 consecutive missed syncs
ANY ───────────────────────► REMOVED
                                                   PULLING (during /api/pull)
                                                       │
                                                       ▼
                                                   AUTO / NOT_INSTALLED
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/local/runtime/info` | node summary + reachable flag |
| GET    | `/local/models?node_id&enabled&top&family&limit` | catalog list |
| GET    | `/local/models/top?node_id&limit` | top-recommended |
| POST   | `/local/models/sync` | trigger a node sync |
| POST   | `/local/models/manual` | add row by hand (planned pulls, etc.) |
| POST   | `/local/models/{router_id}/enable` | flip enabled |
| POST   | `/local/models/{router_id}/pin` | admin pin |
| POST   | `/local/models/{router_id}/test` | live 1-token probe |
| DELETE | `/local/models/{router_id}` | delete manual row |
| POST   | `/local/models/pull` | start `ollama pull` |
| GET    | `/local/models/pull/{model}` | per-pull progress |
| GET    | `/local/models/pulls/active` | all in-flight pulls |
| POST   | `/local/models/pull/cancel` | stop a download (it resumes later) |
| POST   | `/local/models/variant` | an installed model under a new name with a fixed context window |
| GET    | `/local/variants` | every installed model: built from, context window, last load result |
| POST   | `/local/variants` | make a copy (`source`, `context`, optional `name`) |
| POST   | `/local/variants/test` | load a model once and record whether it fits on this machine |
| DELETE | `/local/variants/{name}` | remove a copy (an original is refused) |
| GET    | `/local/library/search?q&source` | search the Ollama library or Hugging Face |
| GET    | `/local/library/tags?name&source&tags` | the builds of one model, with sizes |
| GET    | `/local/library/recommendations` | models that fit this PC (opt-in) |
| PUT    | `/local/library/recommendations` | turn recommendations on or off |
| GET    | `/local/cloud/manifest` | cloud-ingest payload |

All gated by `require_api_key`.

## Get models: search and download

How do you install a model you do not have yet, without a terminal? In the
dashboard, **Model Inventory → Get models** opens a drawer with four tabs.

| Tab | Where it looks | What gets downloaded |
|-----|----------------|----------------------|
| Ollama library | `ollama.com/search` | `qwen2.5:7b` |
| Hugging Face | GGUF repositories, by downloads | `hf.co/<owner>/<repo>:Q4_K_M` |
| For this PC | FitLab's registry, filtered to what fits | the registry's Ollama tag |
| Custom | nothing: you type the reference | any reference Ollama can pull |

A worked example: search `qwen2.5`, open the result, and the drawer lists
each size with its download size, read from the Ollama registry. Press
**Download** on `7b`. The download runs in the gateway, so it continues when
the drawer is closed; reopen it to see progress. When it finishes, the
catalog syncs and the model is routable through `/v1/chat/completions`.

Things worth knowing:

- **The Ollama search is a scrape.** Ollama has no search API, so the search
  page is parsed. If the page changes, search returns nothing; the Custom
  tab still works, because a download by exact name does not use search.
- **Hugging Face shows single-file GGUF builds only.** A model split over
  several files cannot be installed by Ollama from the Hub, so it is hidden.
- **Progress is the sum of a model's files.** Ollama reports each file on
  its own; adding them up keeps the bar from restarting at every file.
- **Cancel keeps what was downloaded.** Starting the same model again
  resumes.

### Recommendations for this PC (off by default)

The "For this PC" tab does nothing until you press **Turn on
recommendations**. From then on it reads this machine's GPU and memory,
downloads FitLab's public `registry.json` from its Hugging Face Space
(cached for a day), and lists the Ollama models that fit, most liked first.
The hardware details stay on the machine: the only request is the download
of that public file.

The estimate is FitLab's (weights + KV cache + runtime overhead, at Q4_K_M
and an 8K context), so a verdict here matches the FitLab leaderboard for the
same hardware. Without a GPU the budget is 60% of system memory.

### A copy with a set context window

Some clients ask for a model by a name that implies its context size. Under
**Custom → Copy with a set context window**, pick an installed model, a
context size and a name. It does what a two-line Modelfile does
(`FROM model`, `PARAMETER num_ctx 8192`) and downloads nothing: the new name
shares the original's files.

## Build a model: copies with their own context window

What do you do when a model does not load because it needs more memory than
the machine has free? Often the model itself fits and its context window
does not: the larger the window, the more memory the model reserves. **Model
Inventory → Build a model** makes a copy of an installed model with a smaller
window, and tells you whether that copy loads.

The wizard has three steps:

1. **Model.** Pick one of the installed models.
2. **Context size.** Pick 2K to 32K, or type another size. Sizes above what
   the model supports are not offered. A size you tried before is marked
   "Loads here" or "Did not load". The name is generated from the model and
   the size (`clef-flash-6k`) and can be changed.
3. **Create and test.** The copy is created, then loaded once. The result
   says whether it loads, how much memory it used, how much of that was on
   the GPU, and how long loading took. If it did not load, **Try 4K
   instead** repeats the step with the next smaller size.

A worked example, from a laptop with 31 GB of memory and a 6 GB GPU:

| Model | Built from | Context | Loads here |
|-------|------------|---------|------------|
| `clef-flash:9b` | the library build `clef-flash:9b-q8_0` | 16,384 | No |
| `clef-flash-8k` | `clef-flash:9b` | 8,192 | No |
| `clef-flash-6k` | `clef-flash:9b` | 6,144 | Yes |

The same table is on Model Inventory under **Model copies**, with **Test**,
**Copy** and (for a copy) **Remove** on every row.

Things worth knowing:

- **A copy takes no disk space.** It is what a two-line Modelfile makes
  (`FROM model`, `PARAMETER num_ctx 6144`): a new name that points at the
  original's files.
- **A copy of a copy is built on the original**, so "Built from" always names
  the model that owns the files.
- **"Loads here" is a measurement of that moment.** It depends on the memory
  free when the test ran, so the same copy can load after you close other
  applications and fail when memory is short. Press **Test** to measure
  again; the row shows when it was last tested.
- **Each kind of model is loaded its own way.** A chat model gets a one-token
  request, an embedding model one embedding, and a decision model (such as
  `clef-flash`) one question on `/v1/systemone`.
- **A test loads the model**, which can push another loaded model out of
  memory. Ollama unloads it again after its usual idle time.
- **Only a copy can be removed here.** Removing an original would delete its
  files, so the gateway refuses it.
- The last result per model is kept in `model_load_tests.json` in the data
  folder.

## CLI

```bash
python -m ollabridge.addons.local_catalog sync
python -m ollabridge.addons.local_catalog stats
python -m ollabridge.addons.local_catalog show --limit 5
python -m ollabridge.addons.local_catalog pull qwen2.5:14b
python -m ollabridge.addons.local_catalog test local:qwen2.5:14b
```

## Configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `OBRIDGE_LOCAL_CATALOG_PATH` | `local_models.yaml` in the data directory | YAML path |
| `OBRIDGE_LOCAL_ALIAS_PATH`   | `local_aliases.yaml` in the data directory | managed aliases |
| `OBRIDGE_LOCAL_SYNC_ENABLED` | `true` | background scheduler |
| `OBRIDGE_LOCAL_SYNC_INTERVAL_S` | `60` | scheduler cadence |
| `OBRIDGE_LOCAL_SYNC_INITIAL_S` | `5` | first-tick delay |
| `OBRIDGE_FITLAB_RECOMMENDATIONS` | `false` | default for "For this PC" on a machine that never chose; the UI switch overrides it |
| `OBRIDGE_FITLAB_REGISTRY_URL` | FitLab's Hugging Face Space | a mirror of FitLab's `registry.json`, tried first |
| `OBRIDGE_LOCAL_AUTO_ENABLE` | `3` | how many to auto-promote |

The data directory is `OLLABRIDGE_HOME` when set, else `DATA_DIR`, else
`~/.ollabridge`.

## Cloud integration

The `CloudBridgeManager.set_local_catalog()` hook is wired during startup
so every heartbeat the bridge sends to the cloud carries a `local_catalog`
manifest:

```json
{
  "type": "hello",
  "models": ["qwen2.5:14b", "llama3.1:8b", "nomic-embed-text"],
  "capabilities": ["chat", "models", "media_fetch"],
  "local_catalog": {
    "node_id": "local-node-01",
    "execution_location": "local",
    "stats": {...},
    "models": [
      {
        "router_model_id": "local-node-01:qwen2.5:14b",
        "external_model_id": "qwen2.5:14b",
        "family": "qwen2.5",
        "parameter_size": "14b",
        "quantization": "q4_K_M",
        "supports_chat": true,
        "supports_tools": true,
        "supports_vision": false,
        "enabled": true,
        "is_top_recommended": true,
        "rank": 1,
        "score": 0.83,
        "setup_status": "verified",
        "latency_ms": 220.0
      },
      ...
    ]
  }
}
```

Cloud Admin's "Local Providers" section reads from this manifest; no
extra endpoint roundtrips are needed beyond the standing WebSocket.

## Routing & privacy

- **Cloud never calls `http://localhost:11434` directly.** All routing
  goes through the existing relay link, exactly as for chat completions.
- The catalog only exposes models to the cloud when the operator's bridge
  is connected. Unlinking via `/admin/cloud/unlink` immediately stops the
  manifest from being shipped.
- Manually-added rows survive `/api/tags` misses (an operator may pin a
  model they plan to pull later).
