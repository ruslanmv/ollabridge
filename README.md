# OllaBridge (Production / Viral Edition)

**Get a private, OpenAI-compatible AI API on your localhost in ~60 seconds.**
Optionally share it (tunnel) so your website can use **your PC** as the default LLM provider.

## What it does

OllaBridge is a **local-first, security-first** gateway that sits in front of Ollama and exposes:

- `POST /v1/chat/completions` (OpenAI-compatible)
- `POST /v1/embeddings` (OpenAI-compatible)
- `GET /health`
- `GET /admin/recent` (requires API key)

### Security defaults

- ✅ API key required (supports both `X-API-Key` and `Authorization: Bearer ...`)
- ✅ Rate limiting enabled
- ✅ Logs stored locally (SQLite default)

## 60-second usage

```bash
pip install ollabridge
ollabridge start --share
```

**Self-healing behavior:**
1. If Ollama is missing → OllaBridge offers to install it (Linux/macOS)
2. If the model is missing → OllaBridge pulls `deepseek-r1`
3. Starts gateway on port `11435`
4. If `--share` and `ngrok` is available → prints a public URL

> For production-grade sharing, prefer Cloudflare Tunnel or Tailscale.

## Use from any OpenAI SDK (your PC becomes the provider)

```python
from openai import OpenAI

client = OpenAI(
  base_url="http://localhost:11435/v1",
  api_key="sk-ollabridge-...",  # sent as Authorization header by the SDK
)

resp = client.chat.completions.create(
  model="deepseek-r1",
  messages=[{"role":"user","content":"Hello from my PC model!"}]
)

print(resp.choices[0].message.content)
```

## Scaling up

- More workers: `ollabridge start --workers 4`
- Better DB: set `DATABASE_URL=postgresql://...` in `.env`

## Dev / local run

```bash
cp .env.example .env
pip install -e .
ollabridge start
```
