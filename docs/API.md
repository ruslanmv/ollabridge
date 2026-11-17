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
| `/v1/systemone` | POST | Decision requests for a decision model such as `clef-flash`, passed through to Ollama. See [Decision requests](#decision-requests) |

Each `/v1/models` entry is an OpenAI model object (`id`, `object`, `owned_by`)
plus two OllaBridge extras that say where this gateway serves it from:

| Field | Meaning |
|-------|---------|
| `source` | `ollama`, `homepilot`, `relay`, `direct_endpoint`, `open_webui`, or `byok:<source name>` (an account connected in Sources, e.g. `byok:watsonx`) |
| `source_display_name` | Human label for the source when known, e.g. `Ollama`, `IBM watsonx` |

`owned_by` is `ollama` for local Ollama models; a provider that sets its own
owner (Open WebUI's namespace, a BYOK source's display name) keeps it. Clients
that only know the OpenAI shape can ignore the extras.

### Decision requests

`POST /v1/systemone` is for decision models (`clef-flash` and copies of it).
A decision model does not write text: it reads a `state` and answers typed
`questions` with a probability per option. Ollama 0.35.1 and later serves this
endpoint; the gateway passes the request and the answer through unchanged, so
a client outside the machine (a container, another host) needs only the
gateway's address and API key.

```bash
curl http://localhost:11435/v1/systemone \
  -H "Authorization: Bearer your-key" -H "Content-Type: application/json" \
  -d '{"model": "clef-flash-8k",
       "state": {"conversation": "Customer: how do I reset my mailbox password?"},
       "questions": {"is_request": {"type": "noul",
                                    "instructions": "Is `conversation` a customer request?"}}}'
```

```json
{"answers": {"is_request": {"type": "noul", "noul": 0.97}}}
```

| Answer | Meaning |
|--------|---------|
| Ollama's own status and body | Returned as they are: `404` when the model is not installed, `500` when it could not be loaded |
| `400` | The body is not a JSON object, or has no `model` or no `questions` |
| `502 ollama_unreachable` | Ollama could not be reached; `base_url` is the address that was tried |
| `504 ollama_timeout` | Ollama did not answer within `SYSTEMONE_TIMEOUT_S` (default 300 seconds) |

The model must be installed in Ollama under the name the client sends. To give
a client the name it expects with a smaller context window, use Model Inventory
→ Get models → Custom → Copy with a set context window (for example
`clef-flash-8k` from `clef-flash:9b` at 8K).

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
| `/admin/rate-limits` | GET | Rate-limit settings, every provider they can apply to, and live state (running, waiting, recent rate-limited answers, cooldowns, refused clients) |
| `/admin/rate-limits` | PUT | Replace the rate-limit settings; applied at once. See [Rate limits](CONFIGURATION.md#rate-limits) |

A rate-limited call, whether by a provider or by OllaBridge's own limits, is
answered with HTTP 429, `code: "rate_limited"` and a `Retry-After` header that
says how long to back off.

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

