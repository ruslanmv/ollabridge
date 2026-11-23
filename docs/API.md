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
| `/v1/systemone` | POST | Decision requests for a decision model, passed through to Ollama or to a source that hosts the model. See [Decision requests](#decision-requests) |

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

`POST /v1/systemone` is for decision models.
A decision model does not write text: it reads a `state` and answers typed
`questions` with a probability per option. Ollama 0.35.1 and later serves this
endpoint; the gateway passes the request and the answer through unchanged, so
a client outside the machine (a container, another host) needs only the
gateway's address and API key.

```bash
curl http://localhost:11435/v1/systemone \
  -H "Authorization: Bearer your-key" -H "Content-Type: application/json" \
  -d '{"model": "my-decision-model",
       "state": {"text": "How do I reset my password?"},
       "questions": {"is_request": {"type": "noul",
                                    "instructions": "Is `text` a question?"}}}'
```

```json
{"answers": {"is_request": {"type": "noul", "noul": 0.97}}}
```

| Answer | Meaning |
|--------|---------|
| The host's own status and body | Returned as they are: `404` when the model is not there, `500` when it could not be loaded |
| `400` | The body is not a JSON object, or has no `model` or no `questions` |
| `502 ollama_unreachable` | Ollama could not be reached; `base_url` is the address that was tried |
| `502 upstream_unreachable` | A source could not be reached; `source` is its name (its address is not shown) |
| `504 ollama_timeout` / `upstream_timeout` | The host did not answer within `SYSTEMONE_TIMEOUT_S` (default 300 seconds) |

For a model in Ollama, it must be installed under the name the client sends.
To give a client the name it expects with a smaller context window, use Model
Inventory → Build a model.

#### Decision models on another server

A decision model does not have to run on this machine. Any server that takes
the same request (`state` and `questions`, answered with `answers`) can be the
host. In **Sources**, open the advanced settings of the source and fill in
**Decision endpoint**. The field is on the Generic OpenAI-compatible source, and
on any other OpenAI-compatible source once its base URL points at a server of
your own. It takes the path under the
source's base URL (`/classify`), or a full URL. The source's API key is sent as
`Authorization: Bearer`, with its custom headers.

Which host answers a request:

| The request's `model` | Answered by |
|-----------------------|-------------|
| `custom/my-decision-model` (the source's name, a slash, the model) | That source; the prefix is removed before sending |
| A model installed in Ollama | Ollama |
| Any other model | Each source with a decision endpoint, in the order they were added; the first that knows the model answers |
| Any model, with no such source | Ollama, as before |

Things worth knowing:

- **Setting the endpoint is the opt-in.** From then on a decision request for
  a model Ollama does not have is sent to that server, with the request's
  text. Leave the field empty, or disable the source, to keep decisions local.
- **Only "I do not have that model" (404) moves on to the next source.** Any
  other answer, such as a rate limit, is returned as it is; the text is not
  sent to a second server because the first was busy.
- **The model listing says what each model is** when the server states it. A
  listing whose entries carry a `kind` (`llm`, `embedding`, `classifier`,
  `speech_to_text`, ...) is believed over a guess from the name, so a
  classifier is not offered as a chat model.

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

