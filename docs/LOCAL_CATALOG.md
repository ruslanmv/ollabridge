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
| GET    | `/local/cloud/manifest` | cloud-ingest payload |

All gated by `require_api_key`.

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
| `OBRIDGE_LOCAL_CATALOG_PATH` | `~/.ollabridge/local_models.yaml` | YAML path |
| `OBRIDGE_LOCAL_ALIAS_PATH`   | `~/.ollabridge/local_aliases.yaml` | managed aliases |
| `OBRIDGE_LOCAL_SYNC_ENABLED` | `true` | background scheduler |
| `OBRIDGE_LOCAL_SYNC_INTERVAL_S` | `60` | scheduler cadence |
| `OBRIDGE_LOCAL_SYNC_INITIAL_S` | `5` | first-tick delay |
| `OBRIDGE_LOCAL_AUTO_ENABLE` | `3` | how many to auto-promote |

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
