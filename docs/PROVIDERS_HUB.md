# Providers Hub — Multi-Provider Alias Routing

Score-based routing across free/cheap hosted providers (Gemini, Groq, OpenRouter,
Hugging Face, DeepSeek) with intent aliases like `free-best`. For BYOK key storage,
rotation, and security see `docs/PROVIDER_KEYS.md`.

---

## Multi-Provider Routing

OllaBridge can route requests beyond local Ollama — to **free**, **cheap**, and **paid** cloud LLM APIs with score-based selection and automatic failover.

### How It Works

When no local node or relay has the requested model, OllaBridge tries the multi-provider addon:

```
Request → Router → Local Ollama / Relay / HomePilot
                 → Provider Addon (if model matches alias or provider)
                     ├── Score candidates by health, latency, tier, quota
                     ├── Try best provider
                     └── Failover to next on error
```

### Supported Providers

| Provider | Category | Notes |
|----------|----------|-------|
| **Google Gemini** | free | Best free overall — large context |
| **Groq** | free | Fastest inference latency |
| **OpenRouter** | free-flex | Aggregator with many free models |
| **Hugging Face** | free-lab | Experimental / OSS inference |
| **DeepSeek** | cheap | Strong reasoning, low cost |
| **Any OpenAI-compatible** | varies | Generic adapter |

### Model Aliases

Use logical names instead of concrete model IDs:

```python
client = OpenAI(base_url="http://localhost:11435/v1", api_key="your-key")

# Alias resolves to best free provider automatically
response = client.chat.completions.create(
    model="free-best",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

Built-in aliases: `free-best`, `free-fast`, `free-flex`, `cheap-reasoning`, `local-private`

### Configuration

Get your free API keys (click, sign up, copy):

| Provider | Get Free Key | Env Variable |
|----------|-------------|--------------|
| **Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | `GEMINI_API_KEY` |
| **Groq** | [console.groq.com/keys](https://console.groq.com/keys) | `GROQ_API_KEY` |
| **OpenRouter** | [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) | `OPENROUTER_API_KEY` |
| **Hugging Face** | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) | `HUGGINGFACE_API_KEY` |
| **DeepSeek** | [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) | `DEEPSEEK_API_KEY` |

Quick setup:

```bash
cp .env.providers.example .env.providers
# Paste your keys in .env.providers
source .env.providers
```

Add or remove providers by editing:

```
src/ollabridge/addons/providers/catalog/providers.seed.yaml
```

### Smoke Testing

```bash
python scripts/test_providers.py
```

Reports health status and latency for each provider.

### Architecture

```
src/ollabridge/addons/providers/
├── adapters/       # Per-provider API translators (Gemini, Groq, etc.)
├── catalog/        # YAML configs (providers, aliases, test matrix)
├── services/       # Loader & seeder
├── router.py       # Score-based routing with failover
├── scoring.py      # Weighted scoring (health/latency/tier/quota/priority)
├── registry.py     # In-memory provider registry
├── health.py       # Health checking
└── quotas.py       # Monthly budget tracking
```

The addon is fully additive — the existing HomePilot/relay/Ollama paths are unchanged. Compatible with the same catalog format used by OllaBridge Cloud.

---

