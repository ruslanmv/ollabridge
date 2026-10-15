# API Reference

HTTP endpoints exposed by the local gateway. All `/v1/*` routes are OpenAI-compatible.
See `docs/EXAMPLES.md` for SDK usage and `docs/CONFIGURATION.md` for auth.

---

## 📡 API Reference

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Gateway health + node count. `local_runtime` reports the Ollama runtime as last seen: `url`, `reachable` (null until probed), `since`, `consecutive_failures`, `last_error` |
| `/v1/chat/completions` | POST | OpenAI-compatible chat |
| `/v1/embeddings` | POST | Generate embeddings |
| `/v1/models` | GET | List available models (aggregated from nodes) |

Each `/v1/models` entry is an OpenAI model object (`id`, `object`, `owned_by`)
plus two OllaBridge extras that say where this gateway serves it from:

| Field | Meaning |
|-------|---------|
| `source` | `ollama`, `homepilot`, `relay`, `direct_endpoint`, `open_webui`, or `byok:<source name>` (an account connected in Sources, e.g. `byok:watsonx`) |
| `source_display_name` | Human label for the source when known, e.g. `Ollama`, `IBM watsonx` |

`owned_by` is `ollama` for local Ollama models; a provider that sets its own
owner (Open WebUI's namespace, a BYOK source's display name) keeps it. Clients
that only know the OpenAI shape can ignore the extras.

### Admin Endpoints (require API key)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/recent` | GET | Recent request logs |
| `/admin/runtimes` | GET | List connected nodes |
| `/admin/enroll` | POST | Create enrollment token |
| `/admin/ollama-setup/status` | GET | "Set up Ollama" wizard: binary, service, nearby addresses, install plan, recommended step |
| `/admin/ollama-setup/install` | POST | Run the platform's official Ollama installer as a background job (fixed command, never user input) |
| `/admin/ollama-setup/jobs/{id}` | GET | Install job status and log lines |
| `/admin/ollama-setup/start` | POST | Launch `ollama serve` detached and wait for it to answer |
| `/admin/ollama-setup/pull` | POST | Pull a first model against the runtime's URL (`{"model": "llama3.2:3b"}`); `GET /pull/{model}` reports progress |

### Example: Check Connected Nodes

```bash
curl -H "X-API-Key: your-key" http://localhost:11435/admin/runtimes
```

**Response:**
```json
{
  "runtimes": [
    {
      "node_id": "local",
      "connector": "local_ollama",
      "healthy": true,
      "tags": ["local"],
      "models": ["deepseek-r1", "llama3.1"]
    },
    {
      "node_id": "colab-gpu-1",
      "connector": "relay_link",
      "healthy": true,
      "tags": ["gpu", "free"],
      "models": ["mixtral", "codellama"]
    }
  ]
}
```

---

