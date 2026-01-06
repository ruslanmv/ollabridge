<div align="center">

<img src="assets/logo.svg" alt="OllaBridge Logo" width="500"/>

# OllaBridge ⚡️

**Your single gateway to ALL your LLMs — local, remote, anywhere.**

[![PyPI version](https://badge.fury.io/py/ollabridge.svg)](https://badge.fury.io/py/ollabridge)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[Quick Start](#-60-second-start) • [Why OllaBridge](#-why-ollabridge) • [Distributed Compute](#-add-any-gpu-in-60-seconds) • [Examples](#-use-it-anywhere) • [Demo Client](#-try-the-interactive-demo-client) • [MCP Mode](#-ai-agents-love-ollabridge)

</div>

---

## 🎯 What is OllaBridge?

> **One gateway. All your LLMs. Everywhere.**

OllaBridge is your **single, OpenAI-compatible API** for every LLM you run — on your laptop, workstation, free GPU servers, cloud instances, anywhere.

**The Problem:** You have models running everywhere (laptop, cloud GPU, friend's gaming PC), and every app needs different configs.

**OllaBridge Solution:** Apps connect to ONE place. OllaBridge routes to the right compute automatically.

```mermaid
graph TB
    A[Your Apps] -->|OpenAI SDK| B[OllaBridge<br/>Control Plane]

    B -->|Auto Routes| C[Local Laptop<br/>llama3.1]
    B -->|Auto Routes| D[Free GPU Cloud<br/>deepseek-r1]
    B -->|Auto Routes| E[Remote Workstation<br/>mixtral]

    C -.->|Dials Out| B
    D -.->|Dials Out| B
    E -.->|Dials Out| B

    style B fill:#6366f1,stroke:#4f46e5,stroke-width:3px,color:#fff
    style A fill:#10b981,stroke:#059669,stroke-width:2px,color:#fff
    style C fill:#8b5cf6,stroke:#7c3aed,stroke-width:2px,color:#fff
    style D fill:#ec4899,stroke:#db2777,stroke-width:2px,color:#fff
    style E fill:#f59e0b,stroke:#d97706,stroke-width:2px,color:#fff
```

**Key Innovation:** Compute nodes **dial out** to your gateway. No port forwarding, no VPN, no config hell.

---

## 🚀 Why OllaBridge?

### 🎯 **Single Source of Truth**
- ✅ **One URL for everything** — Your apps never change code
- ✅ **Zero config** — Add new GPUs without touching your app
- ✅ **Smart routing** — OllaBridge picks the best node automatically
- ✅ **OpenAI compatible** — Works with any SDK, framework, or tool

### 🛡️ **Enterprise-Grade Security**
- ✅ **API key authentication** — Protect your LLMs
- ✅ **Rate limiting** — Control usage per key
- ✅ **Request logging** — Full audit trail
- ✅ **Encrypted connections** — TLS for remote nodes

### 🌍 **Works Everywhere**
- ✅ **Free GPU clouds** — Colab, Kaggle, Lightning AI (no port forwarding needed!)
- ✅ **Ephemeral instances** — Nodes dial out, IPs don't matter
- ✅ **Behind firewalls** — Your laptop can join from coffee shop WiFi
- ✅ **Mixed environments** — Combine local + cloud seamlessly

### 🤖 **AI Agent Ready**
- ✅ **MCP server** — Agents can control your infrastructure
- ✅ **Tool exposure** — Manage nodes, routes, health via tools
- ✅ **Self-healing** — Auto-install, auto-configure, auto-recover

---

## ⚡ 60-Second Start

### Step 1: Install

```bash
pip install ollabridge
```

### Step 2: Start Your Gateway

```bash
ollabridge start
```

**That's it!** You'll see:

```
✅ Ollama installed (if needed)
✅ Model downloaded (if needed)
✅ Gateway online at http://localhost:11435

╭─────────────────── 🚀 Gateway Ready ────────────────────╮
│                                                          │
│ ✅ OllaBridge is Online                                  │
│                                                          │
│ Model:        deepseek-r1                                │
│ Local API:    http://localhost:11435/v1                 │
│ Key:          sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA        │
│                                                          │
│ Node join token:  eyJ0eXAi...                           │
│ Example node command:                                    │
│   ollabridge-node join --control http://localhost:11435 │
│                        --token eyJ0eXAi...              │
│                                                          │
╰──────────────────────────────────────────────────────────╯
```

### Step 3: Use It!

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA"
)

response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Hello!"}]
)

print(response.choices[0].message.content)
```

**Done!** You're running private LLMs with the OpenAI API.

---

## 🌍 Add Any GPU in 60 Seconds

Have a free GPU on Colab? A remote workstation? Add it instantly:

### On Your Remote GPU/Machine:

```bash
# Install
pip install ollabridge

# Join your gateway (copy the command from gateway startup)
ollabridge-node join \
  --control http://YOUR_GATEWAY_IP:11435 \
  --token eyJ0eXAi...
```

**That's it!** The remote GPU:
- ✅ Auto-installs Ollama if needed
- ✅ Auto-downloads models if needed
- ✅ **Dials out** to your gateway (no port forwarding!)
- ✅ Shows up as available compute

### Your Apps See It Automatically

```python
# Same code, now uses both local + remote GPU!
client = OpenAI(base_url="http://localhost:11435/v1", ...)
response = client.chat.completions.create(...)  # Auto-routed
```

**OllaBridge routes requests** across all your nodes automatically.

---

## 🎯 Real-World Scenarios

### Scenario 1: "I have a gaming PC at home"

```bash
# On your gaming PC:
ollabridge-node join --control https://your-gateway.com --token ...

# Now your laptop can use your gaming PC's GPU
# Even if you're at a coffee shop!
```

### Scenario 2: "I want to use free Colab GPUs"

```python
# In Colab notebook:
!pip install ollabridge
!ollabridge-node join --control https://your-gateway.com --token ...

# Now your production app can use free Colab compute
# Colab session ends? Start a new one. Zero config changes.
```

### Scenario 3: "I have multiple cloud GPUs"

```bash
# Each GPU instance:
ollabridge-node join --control https://gateway.company.com --token ...

# Your team shares one API URL
# OllaBridge load-balances across all GPUs
```

---

## 💻 Use It Anywhere

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-key-here"
)

# Chat
response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Explain quantum computing"}]
)

# Embeddings
embeddings = client.embeddings.create(
    model="nomic-embed-text",
    input="Hello, world!"
)
```

### Node.js / TypeScript

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:11435/v1",
  apiKey: process.env.OLLABRIDGE_KEY
});

const completion = await client.chat.completions.create({
  model: "deepseek-r1",
  messages: [{ role: "user", content: "Hello!" }]
});
```

### LangChain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-key-here",
    model="deepseek-r1"
)

response = llm.invoke("What is the meaning of life?")
```

### cURL

```bash
curl -X POST http://localhost:11435/v1/chat/completions \
  -H "Authorization: Bearer your-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-r1",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

**Works with ANY OpenAI-compatible tool or library.**

---

## 🎨 Try the Interactive Demo Client

Want to see OllaBridge in action? Check out our **2-click demo client** in the `example/` folder!

### ⚡ Quick Start

```bash
# 1. Install and start OllaBridge
cd example
./install-ollabridge.sh  # Mac/Linux
# or
.\install-ollabridge.ps1  # Windows

# 2. Run the demo client
make run

# 3. Open http://localhost:3000 in your browser
```

### ✨ Features

- 🎯 **Beautiful UI** — Modern, responsive web interface
- 🔌 **Real Integration** — Actual API calls to OllaBridge endpoints
- 📊 **Live Metrics** — Request stats, latency, uptime tracking
- 🔑 **Auth Demo** — See how API key authentication works
- 📝 **Best Practices** — Production-ready code examples

### 📚 Perfect for Learning

The example client shows you:
- ✅ How to connect to OllaBridge from a browser
- ✅ How to handle CORS properly
- ✅ How to implement authentication with API keys
- ✅ How to load models dynamically
- ✅ How to send chat requests and handle responses

**[View Full Documentation →](example/README.md)**

---

## 🤖 AI Agents Love OllaBridge

OllaBridge has a **Model Context Protocol (MCP) server** built-in.

Agents can:
- ✅ Create enrollment tokens
- ✅ List connected compute nodes
- ✅ Check gateway health
- ✅ Manage your LLM infrastructure via tools

### Start MCP Server

```bash
ollabridge-mcp
```

### Example: Agent Workflow

```python
# Agent can call these tools:
await session.call_tool("ollabridge.enroll.create", {})
# → Returns enrollment token

await session.call_tool("ollabridge.runtimes.list", {})
# → Shows all connected nodes

await session.call_tool("ollabridge.gateway.health", {})
# → Checks gateway status
```

**Use Case:** "Hey Claude, add my workstation's GPU to our LLM gateway"

→ Agent creates token, gives you the command, you run it. Done.

---

## 🔐 Security & Configuration

### Authentication

OllaBridge auto-generates a secure API key on first run (saved in `.env`):

```env
API_KEYS=sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA
```

Use it in your apps:

```python
# Option 1: Bearer token
headers = {"Authorization": "Bearer sk-ollabridge-..."}

# Option 2: Custom header
headers = {"X-API-Key": "sk-ollabridge-..."}
```

### Configuration (`.env`)

```env
# API Keys (comma-separated for multiple)
API_KEYS=sk-ollabridge-abc123,sk-ollabridge-def456

# Server
HOST=0.0.0.0
PORT=11435

# Default models
DEFAULT_MODEL=deepseek-r1
DEFAULT_EMBED_MODEL=nomic-embed-text

# Rate limiting
RATE_LIMIT=60/minute

# Security
ENROLLMENT_SECRET=your-secret-here
ENROLLMENT_TTL_SECONDS=3600

# Database (optional)
DATABASE_URL=postgresql://user:pass@localhost/ollabridge
```

### Enrollment Tokens

Create short-lived tokens for nodes to join:

```bash
ollabridge enroll-create --ttl 3600
```

Tokens expire automatically for security.

---

## 📡 API Reference

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Gateway health + node count |
| `/v1/chat/completions` | POST | OpenAI-compatible chat |
| `/v1/embeddings` | POST | Generate embeddings |
| `/v1/models` | GET | List available models (aggregated from nodes) |

### Admin Endpoints (require API key)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/recent` | GET | Recent request logs |
| `/admin/runtimes` | GET | List connected nodes |
| `/admin/enroll` | POST | Create enrollment token |

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

## 🏗️ Architecture Deep Dive

### How It Works

1. **Control Plane (Gateway)**: Your apps connect here
2. **Nodes**: Any machine with GPUs/CPUs running models
3. **Relay Link**: Nodes dial OUT to gateway (WebSocket)
4. **Router**: Picks the best node for each request

### Why "Dial Out" Matters

**Traditional (broken):**
```
App → Gateway → Try to reach GPU
                ❌ Blocked by firewall
                ❌ NAT issues
                ❌ No public IP
```

**OllaBridge (works everywhere):**
```
App → Gateway ← GPU dials in
               ✅ Works from anywhere
               ✅ No port forwarding
               ✅ Ephemeral IPs OK
```

### Connector Types

- **RelayLink**: Node dials out via WebSocket (default, works everywhere)
- **DirectEndpoint**: HTTP to stable node (best performance)
- **LocalOllama**: Built-in local runtime (zero config)

OllaBridge picks the right one automatically.

---

## 📈 Scaling

### Add More Workers

```bash
ollabridge start --workers 4
```

### Use PostgreSQL

```bash
pip install psycopg2-binary
export DATABASE_URL=postgresql://user:pass@localhost/ollabridge
ollabridge start --workers 8
```

### Add More Nodes

```bash
# Just keep adding nodes!
ollabridge-node join --control ... --token ...
```

OllaBridge automatically load-balances across all healthy nodes.

---

## 🌍 Public Access (Optional)

### Quick Demo (Ngrok)

```bash
ollabridge start --share
```

### Production (Cloudflare Tunnel)

```bash
# Terminal 1: Start gateway
ollabridge start

# Terminal 2: Expose it
cloudflared tunnel --url http://localhost:11435
```

Now your gateway has a public `https://` URL!

**Security:** Always use API keys for public gateways.

---

## 🎓 Beginner's Guide

### "I've never used LLMs before"

1. Install: `pip install ollabridge`
2. Start: `ollabridge start`
3. Copy the API key from the output
4. Use this code:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="PASTE_KEY_HERE"
)

response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Explain Python in simple terms"}]
)

print(response.choices[0].message.content)
```

**That's it!** You're running AI models on your computer.

### "I want to add my gaming PC's GPU"

1. On your main computer (gateway):
   ```bash
   ollabridge start
   # Copy the "Node join token" and gateway URL
   ```

2. On your gaming PC:
   ```bash
   pip install ollabridge
   ollabridge-node join --control http://GATEWAY_IP:11435 --token TOKEN_HERE
   ```

3. Done! Your apps can now use your gaming PC's power.

### "I want to use free Colab GPUs"

1. Start your gateway at home:
   ```bash
   ollabridge start --share
   # Note the public URL (https://xxx.ngrok.io)
   ```

2. In Colab notebook:
   ```python
   !pip install ollabridge
   !ollabridge-node join --control https://xxx.ngrok.io --token YOUR_TOKEN
   ```

3. Now your apps use FREE Colab GPUs!

**Pro tip:** When Colab disconnects, just restart and run step 2 again. Zero config changes needed.

---

## 🛠️ CLI Commands Reference

OllaBridge includes powerful CLI commands for diagnostics, testing, and management.

### Diagnostic Commands

#### `ollabridge doctor`
Diagnose your OllaBridge setup (Ollama, gateway, auth, CORS):

```bash
ollabridge doctor
```

**Output:**
```
                     OllaBridge Doctor
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check               ┃ Result                          ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Ollama /api/tags    │ ✅ OK                           │
│ OllaBridge /health  │ ✅ OK                           │
│ API_KEYS configured │ ✅ yes                          │
│ CORS_ORIGINS        │ http://localhost:5173,...       │
│ Auth usage          │ Use Authorization: Bearer <key> │
└─────────────────────┴─────────────────────────────────┘
```

**Use case:** Troubleshooting connection issues, verifying setup before deployment.

#### `ollabridge models`
List available models (requires API key):

```bash
ollabridge models --api-key sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA
```

**Output:**
```
deepseek-r1
llama3.1
mixtral
```

**Use case:** Verify which models are available across all nodes.

#### `ollabridge test-chat`
Send a test chat completion (requires API key):

```bash
# Simple test
ollabridge test-chat "Hello, how are you?" --api-key sk-ollabridge-...

# Specify model
ollabridge test-chat "Explain quantum computing" \
  --model deepseek-r1 \
  --api-key sk-ollabridge-...
```

**Output:**
```
╭─────────── Assistant ───────────╮
│ Hello! I'm doing well, thank    │
│ you for asking. How can I help  │
│ you today?                       │
╰──────────────────────────────────╯
```

**Use case:** Verify end-to-end connectivity, test API keys, validate model responses.

### Gateway Management

#### `ollabridge start`
Start the gateway (standard mode):

```bash
ollabridge start
```

#### `ollabridge start --lan`
Start with LAN URLs displayed (for classroom/shared networks):

```bash
ollabridge start --lan
```

**Output includes:**
```
🌐 LAN Access
LAN API base:    http://192.168.1.50:11435/v1
LAN Health:      http://192.168.1.50:11435/health

Example (with API key):
curl -H 'Authorization: Bearer <API_KEY>' http://192.168.1.50:11435/v1/models
```

**Use case:** Sharing your gateway with other devices on your network (Quest headsets, phones, other laptops).


#### `ollabridge start --share`
Expose a public URL (via ngrok):

```bash
ollabridge start --share
```

**Use case:** Remote access, connecting nodes from anywhere.

#### `ollabridge enroll-create`
Create enrollment tokens for nodes:

```bash
ollabridge enroll-create --ttl 3600
```

### Quick Tasks

| Task | Command |
|------|---------|
| **List models (API)** | `ollabridge models --api-key <key>` |
| **Test connectivity** | `ollabridge test-chat "test" --api-key <key>` |
| **Check health** | `curl http://localhost:11435/health` |
| **Diagnose setup** | `ollabridge doctor` |
| **See nodes** | `curl -H "X-API-Key: <key>" http://localhost:11435/admin/runtimes` |
| **View logs** | `curl -H "X-API-Key: <key>" http://localhost:11435/admin/recent` |
| **Create token** | `ollabridge enroll-create` |


### For Developers

OllaBridge requires an API key to authenticate requests. If no `.env` file is provided, or the `.env` file does not contain `API_KEYS`, OllaBridge will automatically generate a **temporary, per-run secret API key** (`sk-ollabridge-...`), print it to the screen, and use it only for the current run so you can start developing immediately. **This key is not written to disk by default**, which prevents accidental persistence of credentials and improves security. If you explicitly want OllaBridge to persist the generated API key, you must opt in by starting the gateway with:

```bash
ollabridge start --write-env
```

In this case, OllaBridge will write the generated key to `.env`. For production deployments, it is strongly recommended to set `API_KEYS` using **environment variables or a secure secret manager**, rather than relying on a `.env` file. This design provides safe defaults while avoiding unintentionally storing sensitive information.


---

## ☁️ Optional: OllaBridge Cloud

OllaBridge Local can **optionally** connect to **OllaBridge Cloud** for multi-user, multi-device deployments.

### Cloud Features

- 🔐 **Secure device pairing** with user approval
- 👥 **Multi-user support** with device ownership
- 🌍 **No port forwarding needed** (devices dial out to Cloud)
- 📱 **Multi-device per user** (PC + Quest + phone, etc.)
- 🔄 **Streaming support** for real-time responses

### Pairing Your Device with Cloud

```bash
# 1. Pair this device with OllaBridge Cloud
ollabridge-node cloud-pair --cloud https://your-cloud-url.com

# Shows pairing code - approve via web UI

# 2. Connect to Cloud (uses saved credentials)
ollabridge-node cloud-connect
```

**How it works:**
1. `cloud-pair` gets a pairing code from Cloud
2. You approve the code via Cloud's web UI
3. Device credentials saved to `~/.ollabridge/cloud_device.json`
4. `cloud-connect` connects your device to Cloud relay
5. Cloud routes requests to your device securely

### Local Mode (Default) vs Cloud Mode

| Feature | Local Mode | Cloud Mode |
|---------|------------|------------|
| **Setup** | `ollabridge-node join --control <gateway> --token <token>` | `ollabridge-node cloud-pair --cloud <url>` |
| **Authentication** | Enrollment token | Device pairing + approval |
| **Users** | Single self-hosted | Multi-user cloud accounts |
| **Devices** | Manual node management | Per-user device ownership |
| **Streaming** | Not yet | ✅ Supported |
| **Port forwarding** | Not needed (outbound) | Not needed (outbound) |

**Both modes work together!** Run local gateway + nodes for self-hosting, and optionally pair devices with Cloud for multi-user scenarios.

---

## 🗺️ Roadmap

- [x] ✅ Control Plane + Node architecture
- [x] ✅ Outbound-only node enrollment (no port forwarding)
- [x] ✅ MCP server for AI agent control
- [x] ✅ Multi-node load balancing
- [x] ✅ Diagnostic CLI commands (doctor, models, test-chat)
- [x] ✅ Enhanced CORS handling for browser clients
- [x] ✅ LAN mode for classroom/shared network deployments
- [x] ✅ Cloud compatibility (optional device pairing)
- [x] ✅ Streaming support for chat completions (Cloud mode)
- [ ] 🚧 Tag-based routing (send "coding" requests to GPU nodes)
- [ ] 🚧 Model-specific routing rules
- [ ] 🚧 Web UI for node management
- [ ] 🚧 Prometheus metrics
- [ ] 🚧 Support for more runtimes (vLLM, llama.cpp, LM Studio)

---

## 🤝 Contributing

We welcome contributions! Areas we'd love help:

- 🔌 More runtime adapters (vLLM, llama.cpp, etc.)
- 🎨 Web UI for management
- 📊 Better monitoring/metrics
- 🔒 Security enhancements
- 📖 Documentation improvements

**How to contribute:**

1. Fork the repo
2. Create a branch (`git checkout -b feature/amazing`)
3. Make your changes
4. Add tests
5. Submit a PR

---

## 📄 License

Apache License 2.0 - see [LICENSE](LICENSE)

---

## 🙏 Built With

- [FastAPI](https://fastapi.tiangolo.com/) — Modern async web framework
- [Ollama](https://ollama.ai/) — Run LLMs locally
- [WebSockets](https://websockets.readthedocs.io/) — Real-time node connections
- [SQLModel](https://sqlmodel.tiangolo.com/) — Database with Python types

---

## 💬 Support

- 📖 [Documentation](docs/)
- 🐛 [Report Bug](https://github.com/ruslanmv/ollabridge/issues)
- 💡 [Request Feature](https://github.com/ruslanmv/ollabridge/issues)
- 💬 [Discussions](https://github.com/ruslanmv/ollabridge/discussions)

---

## 🌟 Star History

If OllaBridge helped you, give it a star! ⭐

---

<div align="center">

**Made with ❤️ for the local-first AI community**

**Stop paying cloud tokens. Use your own compute.**

</div>
