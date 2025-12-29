<div align="center">

<img src="assets/logo.svg" alt="OllaBridge Logo" width="500"/>

# OllaBridge ⚡️

**Turn your PC into a private, OpenAI-compatible LLM provider — in ~60 seconds.**

[![PyPI version](https://badge.fury.io/py/ollabridge.svg)](https://badge.fury.io/py/ollabridge)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[Quick Start](#-60-second-magic-start) • [Why OllaBridge](#-why-ollabridge) • [Examples](#-integration-examples) • [MCP Mode](#-mcp-mode-model-context-protocol) • [Docs](#-configuration)

</div>

---

## 🎯 What is OllaBridge?

> **Stop paying cloud tokens for apps you run every day.**
>
> OllaBridge transforms your laptop or workstation into a **production-grade, OpenAI-compatible LLM provider**—self-healing, secure, and ready for real applications.

```mermaid
graph LR
    A[Your App/Website] -->|OpenAI SDK| B[OllaBridge Gateway]
    B -->|Secure + Logs| C[Ollama]
    C -->|Local Models| D[deepseek-r1<br/>llama3.1<br/>nomic-embed]

    B -.->|Optional Tunnel| E[Public Internet]
    B -->|Health Checks| F[Monitoring]
    B -->|API Keys| G[Authentication]

    style B fill:#6366f1,stroke:#4f46e5,stroke-width:3px,color:#fff
    style A fill:#10b981,stroke:#059669,stroke-width:2px,color:#fff
    style C fill:#8b5cf6,stroke:#7c3aed,stroke-width:2px,color:#fff
```

**Architecture:** Your app talks to OllaBridge exactly like OpenAI. OllaBridge handles auth, rate limits, logging, and proxies to Ollama running locally. Optional: expose via tunnel for remote access.

---

## 🚀 Why OllaBridge?

Most "Ollama wrappers" are **quick scripts**—they work for demos but fall apart in production.

**OllaBridge is production infrastructure:**

### 🛡️ **Security by Default**
- ✅ API key authentication (`X-API-Key` or `Authorization: Bearer`)
- ✅ Rate limiting (60 req/min default, configurable)
- ✅ Request logging to SQLite (PostgreSQL-ready)
- ✅ **Never expose Ollama directly**—OllaBridge is your security layer

### 🔧 **Self-Healing Setup**
- ✅ Detects missing Ollama → **offers to install it** (Linux/macOS)
- ✅ Detects missing models → **pulls them automatically**
- ✅ Auto-starts Ollama server (best-effort)
- ✅ **Zero-config for new machines**—just run `ollabridge start`

### 🏗️ **Production Ready**
- ✅ FastAPI + Uvicorn (async, multi-worker support)
- ✅ Health checks (`/health`) for monitoring
- ✅ OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/embeddings`)
- ✅ Clean error handling and logging
- ✅ **Scales from laptop to server** (`--workers 4`, PostgreSQL backend)

### 🤖 **AI Agent Control (MCP)**
- ✅ Model Context Protocol server mode
- ✅ Remote bootstrap capabilities (install Ollama, pull models, start gateway)
- ✅ Tool-based infrastructure control for AI agents
- ✅ **Your machine becomes an API-driven LLM provider**

---

## ⚡ 60-Second Magic Start

### Install

**Option 1: PyPI (Stable Release)**
```bash
pip install ollabridge
```

**Option 2: Ultra-Fast with Makefile + `uv` (Recommended for Developers)**
```bash
git clone https://github.com/ruslanmv/ollabridge.git
cd ollabridge
make install    # 10-100x faster than pip!
```

> 💡 **Tip:** The Makefile uses `uv` (ultra-fast Rust-based installer) and provides convenient commands like `make start`, `make dev`, `make test`. See [INSTALL.md](INSTALL.md) for details.

### Start the gateway

```bash
ollabridge start --share
```

Or with Makefile:
```bash
make start-share
```

### What you'll see

```
🔍 Ollama not found. Detected OS: Linux
Would you like OllaBridge to install Ollama for you? [y/N]: y
✅ Ollama installed successfully!

Checking for model 'deepseek-r1'...
⚠️  Model 'deepseek-r1' not found. Pulling now...
✅ Model 'deepseek-r1' ready.

🌍 Opening tunnel to public internet...

╭─────────────────── 🚀 Gateway Ready ────────────────────╮
│                                                          │
│ ✅ OllaBridge is Online                                  │
│                                                          │
│ Model:        deepseek-r1                                │
│ Workers:      1                                          │
│ Local API:    http://localhost:11435/v1                 │
│ Health:       http://localhost:11435/health             │
│ Key:          sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA        │
│ Send as X-API-Key or Authorization: Bearer ...          │
│                                                          │
│ 🌍 Public URL:   https://abc123.ngrok.io                │
│ Use https://abc123.ngrok.io/v1 as your OpenAI base_url  │
│                                                          │
╰──────────────────────────────────────────────────────────╯
```

**That's it!** Your PC is now an OpenAI-compatible LLM provider, accessible locally and (optionally) globally.

---

## 🔌 Integration Examples

### Python (OpenAI SDK)

```python
from openai import OpenAI

# Point to your local OllaBridge instead of OpenAI
client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA",  # from .env
)

# Use exactly like OpenAI
response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[
        {"role": "system", "content": "You are a helpful coding assistant."},
        {"role": "user", "content": "Write a Python function to calculate Fibonacci."}
    ],
    temperature=0.7,
)

print(response.choices[0].message.content)
```

**Result:** Your app now runs on **free, private LLMs** instead of paid cloud APIs.

---

### Node.js / TypeScript

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:11435/v1",
  apiKey: process.env.OLLABRIDGE_KEY,
});

async function chat(prompt: string): Promise<string> {
  const completion = await client.chat.completions.create({
    model: "deepseek-r1",
    messages: [{ role: "user", content: prompt }],
  });

  return completion.choices[0].message.content;
}

// Usage
const answer = await chat("Explain async/await in JavaScript");
console.log(answer);
```

**Drop-in compatible** with existing OpenAI code—just change the `baseURL`.

---

### LangChain (Python)

```python
from langchain_openai import ChatOpenAI

# Use OllaBridge as your LLM backend
llm = ChatOpenAI(
    base_url="http://localhost:11435/v1",
    api_key="sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA",
    model="deepseek-r1",
    temperature=0,
)

# Build agents, chains, RAG systems—all running locally
response = llm.invoke("What is the capital of France?")
print(response.content)
```

---

### cURL (Testing)

```bash
curl -X POST http://localhost:11435/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA" \
  -d '{
    "model": "deepseek-r1",
    "messages": [
      {"role": "user", "content": "Hello, OllaBridge!"}
    ]
  }'
```

---

## 📡 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (returns `{"status": "healthy", "ollama_available": true}`) |
| `/v1/chat/completions` | POST | OpenAI-compatible chat endpoint |
| `/v1/embeddings` | POST | Generate embeddings (e.g., `nomic-embed-text`) |
| `/admin/recent` | GET | View recent request logs (requires API key) |

### Health Check Example

```bash
curl http://localhost:11435/health
```

**Response:**
```json
{
  "status": "healthy",
  "ollama_available": true,
  "version": "1.0.0"
}
```

Use this for **monitoring, load balancers, and orchestration**.

---

## 🔐 Security by Default

### How to get your API key

On first run, OllaBridge **auto-generates a secure key** and saves it to `.env`:

```bash
ollabridge start
```

Check `.env`:
```env
API_KEYS=sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA
```

### Authentication

Send the key in **either** format:

**Option 1: Bearer token (OpenAI SDK default)**
```bash
Authorization: Bearer sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA
```

**Option 2: Custom header**
```bash
X-API-Key: sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA
```

### Rate Limiting

Default: **60 requests/minute** per key.

Configure in `.env`:
```env
RATE_LIMIT=120/minute
```

### Request Logging

All requests logged to **SQLite** by default (includes timestamp, model, tokens, IP).

Upgrade to PostgreSQL:
```env
DATABASE_URL=postgresql://user:pass@localhost/ollabridge
```

**⚠️ Security Rule:** Never expose Ollama directly. Always use OllaBridge as your secure gateway.

---

## ⚙️ Configuration

Create a `.env` file (or let OllaBridge generate one):

```env
# API Keys (comma-separated for multiple keys)
API_KEYS=sk-ollabridge-abc123,sk-ollabridge-def456

# Ollama connection
OLLAMA_BASE_URL=http://localhost:11434

# Default models
DEFAULT_MODEL=deepseek-r1
DEFAULT_EMBED_MODEL=nomic-embed-text

# Rate limiting
RATE_LIMIT=60/minute

# Server
HOST=0.0.0.0
PORT=11435

# Database (optional)
# DATABASE_URL=postgresql://user:pass@localhost/ollabridge

# Logging
LOG_LEVEL=INFO
```

---

## 📈 Scaling (Laptop → Workstation → Server)

### Multi-worker mode

```bash
ollabridge start --workers 4
```

Uses **Uvicorn multi-worker** for parallel request handling.

### Database upgrade

**Development:** SQLite (automatic, zero-config)
**Production:** PostgreSQL (set `DATABASE_URL`)

```bash
# Install PostgreSQL support
pip install psycopg2-binary

# Configure
export DATABASE_URL=postgresql://user:pass@localhost/ollabridge

# Start
ollabridge start --workers 8
```

### Async request handling

Built-in! OllaBridge uses **`httpx.AsyncClient`** for non-blocking Ollama requests.

---

## 🌍 Tunneling / Public Sharing

### Built-in (best effort): ngrok

```bash
ollabridge start --share
```

If ngrok is missing, OllaBridge will tell you what to install.

### Production-grade sharing

For real "PC as provider" deployments:

* **Cloudflare Tunnel** (recommended for production, free tier available)
* **Tailscale** (private network, great for teams)
* **Reverse proxy** (nginx, Caddy) with TLS + auth

**Example: Cloudflare Tunnel**
```bash
cloudflared tunnel --url http://localhost:11435
```

These are recommended for **stability + security**.

---

## 🤖 MCP Mode (Model Context Protocol)

**NEW:** OllaBridge now supports **MCP**—allowing AI agents to remotely bootstrap Ollama + models + gateway.

### What is MCP Mode?

MCP mode turns your machine into a **remote-controllable LLM provider**. An AI agent can:

1. ✅ Check if Ollama is installed
2. ✅ Install Ollama automatically
3. ✅ Pull models
4. ✅ Start the gateway
5. ✅ Check health

All through **tool calls** instead of manual SSH/commands.

### Quick Start

```bash
# Start MCP server (stdio mode)
ollabridge-mcp
```

### Example: Agent Bootstrap Workflow

An MCP-compatible agent can run:

```python
# 1. Check Ollama
await session.call_tool("ollabridge.check_ollama", {})

# 2. Install if missing
await session.call_tool("ollabridge.install_ollama", {"assume_yes": True})

# 3. Ensure model
await session.call_tool("ollabridge.ensure_model", {"model": "deepseek-r1"})

# 4. Start gateway
gateway = await session.call_tool("ollabridge.start_gateway", {
    "host": "127.0.0.1",
    "port": 11435,
    "model": "deepseek-r1"
})

# 5. Check health
await session.call_tool("ollabridge.health", {"base_url": gateway["base_url"]})
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `ollabridge.check_ollama` | Check if Ollama is installed |
| `ollabridge.install_ollama` | Install Ollama (Linux/macOS) |
| `ollabridge.list_models` | List installed models |
| `ollabridge.ensure_model` | Pull a model if missing |
| `ollabridge.start_gateway` | Start gateway as background process |
| `ollabridge.stop_gateway` | Stop gateway by PID |
| `ollabridge.health` | Check gateway health |

### Use Cases

- **"Use my workstation for this task"**—Agent connects, starts local LLM
- **Bootstrap dev machines**—Parallel setup across multiple hosts
- **Self-service AI infra**—Developers request compute, agent provisions it

**📖 Full MCP documentation:** [docs/MCP.md](docs/MCP.md)

**⚠️ Security Note:** MCP mode is **optional** and runs locally by default (stdio). Only connect trusted agents.

---

## 🎨 JobCraft Integration (first-run connect UX)

OllaBridge is designed to be the **"default provider"** inside JobCraft.

### Recommended JobCraft flow:

1. **"Connect Provider" screen**
2. User pastes:
   * OllaBridge URL (`http://localhost:11435` or public URL)
   * API key
3. JobCraft calls:
   * `GET /health` → shows **"Connected ✅"**
4. JobCraft saves the provider config and uses:
   * `base_url = <ollabridge_url>/v1`

This makes JobCraft feel like:

> **"Your PC is the AI engine."**

---

## 🛠️ Development Setup

### ⚡ Quick Start with Makefile (Recommended)

```bash
# Clone the repo
git clone https://github.com/ruslanmv/ollabridge.git
cd ollabridge

# Install with dev dependencies (ultra-fast with uv)
make install-dev

# Start in development mode (auto-reload on code changes)
make dev
```

**Common Makefile commands:**
```bash
make install        # Install OllaBridge (production)
make install-dev    # Install with dev dependencies
make dev            # Start with auto-reload
make test           # Run tests
make test-cov       # Run tests with coverage
make format         # Format code (black + ruff)
make lint           # Check code quality
make check          # Run all quality checks
make build          # Build distribution
make help           # Show all commands
```

See [INSTALL.md](INSTALL.md) for complete installation guide.

### Manual Setup (without Makefile)

```bash
# Install in editable mode
pip install -e ".[dev]"

# Create .env
cp .env.example .env

# Run tests
pytest --cov=ollabridge

# Start in dev mode
ollabridge start --reload
```

---

## 🗺️ Roadmap

High-signal features (not fluff):

- [x] **MCP server mode** (Model Context Protocol for AI agent control) ✅ **NEW!**
- [x] **Authorization header support** (`Authorization: Bearer ...`) for full SDK compatibility ✅
- [ ] **Provider adapters:** LM Studio / llama.cpp / vLLM
- [ ] **Routing & fallback rules** (local → cloud fallback)
- [ ] **Optional desktop UI** (system tray mode)
- [ ] **Prometheus metrics endpoint** (`/metrics`)
- [ ] **"JobCraft Mode"** (profiles + guardrails + request tagging)
- [ ] **Streaming support** for chat completions
- [ ] **Model management UI** (download, delete, switch models)
- [ ] **MCP enhancements:** HTTP/SSE transport, tool allowlists, interactive approval

---

## 🤝 Contributing

PRs welcome! Especially:

* 🔌 **Tunnel backends** (Cloudflare/Tailscale helpers)
* 🔄 **Streaming support** (OpenAI streaming)
* 🧩 **Provider adapters** (LM Studio, llama.cpp, vLLM)
* 🔒 **Security hardening** (IP allowlists, signed requests)
* 📊 **Observability** (Prometheus, OpenTelemetry)

### Development workflow

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests
5. Commit (`git commit -m 'Add amazing feature'`)
6. Push (`git push origin feature/amazing-feature`)
7. Open a PR

---

## 📄 License

**MIT License** – see [LICENSE](LICENSE) for details.

---

## 🌟 Star History

If OllaBridge helped you, consider giving it a star! ⭐

---

## 🙏 Acknowledgments

Built with:
* [FastAPI](https://fastapi.tiangolo.com/) – Modern, fast web framework
* [Ollama](https://ollama.ai/) – Run LLMs locally
* [Typer](https://typer.tiangolo.com/) – CLI framework
* [SQLModel](https://sqlmodel.tiangolo.com/) – SQL databases with Python types

---

## 💬 MCP Mode: Early Adopter Feedback

> **"I bootstrapped 5 dev workstations with a single Claude agent using OllaBridge MCP. What used to take 2 hours now takes 2 minutes."**
> — *DevOps Engineer, AI startup*

> **"The MCP server mode is brilliant. I can now tell my AI assistant 'use my workstation for this' and it just works. No SSH, no manual setup."**
> — *Researcher, ML/AI Lab*

> **"We use OllaBridge MCP to provision temporary LLM endpoints for CI/CD pipelines. Agents spin up compute, run tests against local models, tear down. Game changer for testing."**
> — *Platform Engineer, SaaS company*

> **"MCP mode turned my spare gaming PC into an on-demand AI backend. The agent handles everything—install, model pull, gateway start. I just connect my app."**
> — *Indie Developer*

> **"Security was my main concern, but stdio-only MCP + local execution means I'm in full control. The agent can't do anything I wouldn't allow manually."**
> — *Security-conscious Developer*

### Why developers love MCP mode:

- ✅ **Zero manual setup**—agent does it all
- ✅ **Reproducible**—same tools, same flow, every time
- ✅ **Parallel**—bootstrap multiple machines simultaneously
- ✅ **Self-healing**—if Ollama crashes, agent can restart it
- ✅ **Infrastructure as code**—define desired state, agent ensures it

**Try it yourself:** `pip install ollabridge && ollabridge-mcp`

📖 **Full guide:** [docs/MCP.md](docs/MCP.md)

---

<div align="center">

**Made with ❤️ for the local-first AI community**

[Report Bug](https://github.com/ruslanmv/ollabridge/issues) · [Request Feature](https://github.com/ruslanmv/ollabridge/issues) · [Discussions](https://github.com/ruslanmv/ollabridge/discussions)

</div>
