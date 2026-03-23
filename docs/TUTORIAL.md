# OllaBridge Complete Tutorial

**Your Gateway to Private AI - Run LLMs Everywhere**

---

## 📚 Table of Contents

1. [What is OllaBridge?](#what-is-ollabridge)
2. [Why Should You Care?](#why-should-you-care)
3. [How It Works](#how-it-works)
4. [Getting Started](#getting-started)
5. [For Gamers & Power Users](#for-gamers--power-users)
6. [For Developers](#for-developers)
7. [Cloud Mode (Multi-User)](#cloud-mode-multi-user)
8. [Advanced Usage](#advanced-usage)
9. [Troubleshooting](#troubleshooting)
10. [FAQ](#faq)

---

## What is OllaBridge?

**OllaBridge is your single API gateway to ALL your AI models - running on your laptop, gaming PC, free cloud GPUs, anywhere.**

Think of it as a **smart router for AI**:
- You have models running everywhere (laptop, gaming PC, cloud)
- Every app needs different configs
- **OllaBridge solves this:** Apps connect to ONE place, OllaBridge routes to the right compute automatically

### The Problem OllaBridge Solves

**Before OllaBridge:**
```
Your App ──❌──> Try to connect to laptop (wrong IP)
Your App ──❌──> Try to connect to gaming PC (firewall)
Your App ──❌──> Try to connect to cloud GPU (expired)
Your App ──❌──> Give up
```

**With OllaBridge:**
```
Your App ──✅──> OllaBridge ──> Routes to best available GPU
                  ↓
            (laptop, gaming PC, or cloud - automatically)
```

---

## Why Should You Care?

### For Everyone
- ✅ **Run AI models 100% free** (no OpenAI bills)
- ✅ **Privacy:** Your data never leaves your devices
- ✅ **One API for everything:** Works with ANY app that supports OpenAI
- ✅ **Zero config hell:** Add GPUs without changing your apps

### For Gamers
- ✅ **Use your gaming PC's GPU** for AI when you're not gaming
- ✅ **Access from anywhere:** Use your gaming rig from your laptop, phone, or Quest headset
- ✅ **No port forwarding:** Works behind routers and firewalls
- ✅ **Quest/VR ready:** Run AI in your VR apps with streaming support

### For Developers
- ✅ **OpenAI-compatible API:** Drop-in replacement
- ✅ **Self-healing:** Auto-installs Ollama, auto-downloads models
- ✅ **Multi-node load balancing:** Scale across unlimited GPUs
- ✅ **Free cloud GPUs:** Use Colab/Kaggle without port forwarding

---

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────┐
│  YOUR APPS (Python, JavaScript, curl, anything)     │
│  Use ONE API: http://localhost:11435/v1             │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│  OLLABRIDGE GATEWAY (your computer)                 │
│  - Receives requests                                │
│  - Routes to best GPU                               │
│  - Returns results                                  │
└──────────────┬──────────┬──────────┬────────────────┘
               │          │          │
       ┌───────▼──┐  ┌────▼─────┐  ┌▼──────────┐
       │ Laptop   │  │ Gaming   │  │ Free GPU  │
       │ (local)  │  │ PC       │  │ (Colab)   │
       │ llama3   │  │ deepseek │  │ mixtral   │
       └──────────┘  └──────────┘  └───────────┘
```

### Magic Features

1. **Nodes Dial OUT** (no port forwarding needed)
   - Gaming PC calls Gateway
   - Gateway never calls Gaming PC
   - Works through firewalls automatically

2. **Smart Routing**
   - OllaBridge picks the fastest available GPU
   - If one fails, automatically tries another
   - Load balances across all your machines

3. **Self-Healing**
   - Detects if Ollama isn't installed → installs it
   - Detects if model missing → downloads it
   - Just works™

---

## Getting Started

### Installation (60 Seconds)

#### Step 1: Install OllaBridge

```bash
pip install ollabridge
```

That's it! OllaBridge auto-installs Ollama if needed.

#### Step 2: Start Your Gateway

```bash
ollabridge start
```

**You'll see:**
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
│ Send as X-API-Key or Authorization: Bearer ...          │
│                                                          │
╰──────────────────────────────────────────────────────────╯
```

**Save your API key!** You'll need it for all requests.

#### Step 3: Test It!

##### Option A: Python
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA"  # Use YOUR key
)

response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Explain quantum computing in simple terms"}]
)

print(response.choices[0].message.content)
```

##### Option B: Command Line
```bash
# Using the built-in test command
ollabridge test-chat "Explain quantum computing" --api-key sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA

# Or using curl
curl -X POST http://localhost:11435/v1/chat/completions \
  -H "Authorization: Bearer sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-r1",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Quick Diagnostic Commands

OllaBridge includes helpful diagnostic tools:

```bash
# Check if everything is working
ollabridge doctor

# List available models
ollabridge models --api-key YOUR_KEY

# Test chat completion
ollabridge test-chat "Hello AI!" --api-key YOUR_KEY
```

---

## For Gamers & Power Users

### Use Case 1: "Access My Gaming PC's GPU From Anywhere"

#### On Your Gaming PC:

```bash
# 1. Install OllaBridge on gaming PC
pip install ollabridge

# 2. Start the gateway on gaming PC
ollabridge start --lan

# You'll see your LAN IP:
# LAN API base: http://192.168.1.50:11435/v1
```

#### On Your Laptop/Phone/Quest:

```python
from openai import OpenAI

# Connect to your gaming PC
client = OpenAI(
    base_url="http://192.168.1.50:11435/v1",  # Your gaming PC's IP
    api_key="sk-ollabridge-..."  # Key from gaming PC
)

# Now you're using your gaming PC's GPU from anywhere on your network!
response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Write a story"}]
)
```

### Use Case 2: "Use My Gaming PC When I'm At a Coffee Shop"

You have two options:

#### Option A: Public URL (Quick & Easy)
```bash
# On gaming PC:
ollabridge start --share

# Shows:
# 🌍 Public URL: https://abc123.ngrok.io
```

Now use `https://abc123.ngrok.io/v1` from anywhere in the world!

#### Option B: OllaBridge Cloud (Advanced - see Cloud section)

### Use Case 3: "VR/Quest AI Apps"

OllaBridge supports **streaming** in Cloud mode for real-time AI in VR:

```javascript
// In your Quest app (JavaScript)
const response = await fetch('http://YOUR_GATEWAY/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer YOUR_KEY',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    model: 'deepseek-r1',
    messages: [{role: 'user', content: 'Help me in VR'}],
    stream: true  // Enable streaming for real-time responses
  })
});

// Stream tokens as they arrive
const reader = response.body.getReader();
// ... handle streaming
```

**Important:** Enable CORS for browser/VR apps:
```bash
# In .env file:
CORS_ORIGINS=http://localhost:5173,http://192.168.1.100:3000
```

### Use Case 4: "Multiple GPUs (Load Balancing)"

**Scenario:** You have a gaming PC + laptop + friend's PC

#### Step 1: Start Gateway (Main Computer)
```bash
ollabridge start
# Note the "Node join token" shown
```

#### Step 2: Add Gaming PC as Node
```bash
# On gaming PC:
pip install ollabridge

ollabridge-node join \
  --control http://YOUR_GATEWAY_IP:11435 \
  --token eyJ0eXAi...  # Token from step 1
```

#### Step 3: Add Laptop as Node
```bash
# On laptop:
ollabridge-node join \
  --control http://YOUR_GATEWAY_IP:11435 \
  --token eyJ0eXAi...
```

**Now OllaBridge automatically load-balances across all 3 machines!**

---

## For Developers

### OpenAI SDK Compatibility

OllaBridge is 100% compatible with OpenAI SDK:

#### Python
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="sk-ollabridge-..."
)

# Chat
response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Hello"}]
)

# Embeddings
embeddings = client.embeddings.create(
    model="nomic-embed-text",
    input="Hello world"
)
```

#### JavaScript/TypeScript
```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:11435/v1",
  apiKey: process.env.OLLABRIDGE_KEY
});

const completion = await client.chat.completions.create({
  model: "deepseek-r1",
  messages: [{ role: "user", content: "Hello" }]
});
```

### LangChain Integration
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:11435/v1",
    api_key="sk-ollabridge-...",
    model="deepseek-r1"
)

response = llm.invoke("What is the meaning of life?")
```

### Free Cloud GPUs (Colab/Kaggle)

**Scenario:** You want to use free Colab GPUs without port forwarding

#### Step 1: Start Gateway at Home
```bash
ollabridge start --share
# Note the public URL: https://xyz.ngrok.io
```

#### Step 2: In Colab Notebook
```python
!pip install ollabridge

# Get enrollment token from gateway startup output
!ollabridge-node join \
  --control https://xyz.ngrok.io \
  --token YOUR_TOKEN
```

**When Colab disconnects:** Just re-run step 2. Zero config changes needed!

---

## Cloud Mode (Multi-User)

**OllaBridge Cloud** enables multi-user, multi-device deployments with an enterprise-grade dashboard.

### What is Cloud Mode?

| Feature | Local Mode | Cloud Mode |
|---------|------------|------------|
| **Users** | Single (you) | Multiple users with accounts |
| **Devices** | Manual management | Per-user device ownership |
| **Setup** | Self-hosted | Hosted service or self-hosted |
| **Streaming** | Coming soon | Available |
| **Authentication** | API key tokens | TV-style device pairing |
| **Dashboard** | Local React UI | Enterprise sidebar UI |
| **VR Support** | LAN only | Cloud relay (no port forwarding) |

### Architecture: How Cloud Relay Works

```
Your PC (GPU)              OllaBridge Cloud            Oculus Quest
┌───────────────┐         ┌──────────────┐         ┌─────────────┐
│ Ollama        │         │              │         │ 3D Avatar   │
│ HomePilot     │◄──WSS──►│  Relay Hub   │◄──HTTPS─│ Chatbot     │
│ OllaBridge    │         │              │         │             │
└───────────────┘         └──────────────┘         └─────────────┘
```

1. **Your PC** runs Ollama/HomePilot with the models (your GPU does the work)
2. **OllaBridge Cloud** acts as a relay — it doesn't store data, just routes requests
3. **Quest/Web clients** connect to the cloud URL with standard OpenAI-compatible API
4. **No port forwarding** — your PC dials OUT via WebSocket, works behind any NAT/firewall

### How to Join OllaBridge Cloud

#### Method A: From OllaBridge Dashboard (Recommended)

1. Open your local OllaBridge dashboard at `http://localhost:11435`
2. Click the **Cloud** icon in the sidebar
3. Enter the Cloud URL: `https://ruslanmv-ollabridge.hf.space`
4. Click **"Link to Cloud"**
5. A pairing code appears (e.g., `ABCD-1234`)

#### Method B: From CLI

```bash
ollabridge-node cloud-pair --cloud https://ruslanmv-ollabridge.hf.space
```

**You'll see:**
```
╭─────────────── OllaBridge Cloud Pairing ───────────────╮
│                                                         │
│ User code:     ABCD-1234                                │
│ Verify at:     https://ruslanmv-ollabridge.hf.space/link│
│                                                         │
│ Open the verification URL, log in, and enter the code. │
│ This code expires in ~600 seconds.                     │
│                                                         │
╰─────────────────────────────────────────────────────────╯

⠋ Waiting for approval...
```

#### Step 2: Approve on Cloud Dashboard

1. Open `https://ruslanmv-ollabridge.hf.space/link` (the verification URL)
2. Log in or create an account (email/password or Google OAuth)
3. Enter the 8-character pairing code: `ABCD-1234`
4. Click **"Confirm & Link"**
5. Your PC auto-connects via WebSocket

> **Note:** If you're already logged in, navigating to `/link` takes you directly
> to the code entry page. If not, you'll be redirected to login first and then
> sent back to the linking page automatically.

#### Step 3: Verify Connection

Once approved, your OllaBridge local dashboard shows:
- **Cloud Relay: Connected** with a green status dot
- Number of models shared with the cloud
- Device ID and uptime

The Cloud dashboard (`/dashboard`) shows your device in the sidebar with online/offline status.

### Cloud Dashboard Features

The OllaBridge Cloud dashboard has an **enterprise sidebar layout**:

**Left Sidebar:**
- **Navigation** — Overview, Link Device
- **Devices** — Lists all your paired PCs with online/offline badges
- **Resources** — Documentation, API Status, Admin Panel
- **Settings** — Sign Out
- **User Profile** — Avatar, name, and email at the bottom

**Main Content Area:**
- Server status (Gateway, Ollama, Relay health)
- Stats (Devices, Relay Connections, Models Available, API Endpoint)
- Device cards with rename/delete actions
- Quick Start connection guide

### Cloud API Endpoints

Once connected, clients (Quest VR, web apps) use the cloud URL:

```bash
# Chat with a model through the cloud relay
curl -X POST https://ruslanmv-ollabridge.hf.space/ollama/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:1.5b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'

# List available models (includes relay device models)
curl https://ruslanmv-ollabridge.hf.space/ollama/v1/models

# Chat with a HomePilot persona
curl -X POST https://ruslanmv-ollabridge.hf.space/ollama/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "personality:therapist",
    "messages": [{"role": "user", "content": "I need advice"}]
  }'
```

### Cloud Advantages

- **Multi-device:** Use PC + Quest + phone under one account
- **Team sharing:** Share access with team members
- **Streaming:** Real-time token-by-token responses
- **Enterprise dashboard:** Sidebar layout with device management
- **Web dashboard:** Manage devices, monitor server status
- **No port forwarding:** WebSocket relay works behind any NAT/firewall
- **Google OAuth:** Quick sign-in with Google account
- **HomePilot personas:** Route persona and personality agents through the cloud
- **Federation:** Peer mesh across multiple cloud instances for load balancing

---

## Advanced Usage

### Custom Models

```bash
# Start with specific model
ollabridge start --model llama3.1

# Ensure model exists on node
ollabridge-node join \
  --control http://gateway:11435 \
  --token TOKEN \
  --ensure-model codellama
```

### LAN Mode (Classroom/Network)

Perfect for sharing with students, family, or LAN party:

```bash
ollabridge start --lan
```

Shows:
```
🌐 LAN Access
LAN API base:    http://192.168.1.50:11435/v1
LAN Health:      http://192.168.1.50:11435/health

Example (with API key):
curl -H 'Authorization: Bearer <API_KEY>' http://192.168.1.50:11435/v1/models
```

**Everyone on your network can now use your gateway!**

### Environment Configuration

Create `.env` file:

```env
# API Keys (comma-separated for multiple)
API_KEYS=sk-ollabridge-abc123,sk-ollabridge-def456

# Server
HOST=0.0.0.0
PORT=11435

# CORS (for browser apps)
CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# Models
DEFAULT_MODEL=deepseek-r1
DEFAULT_EMBED_MODEL=nomic-embed-text

# Rate limiting
RATE_LIMIT=60/minute
```

### Multiple Workers (Scalability)

```bash
# Run with 4 worker processes
ollabridge start --workers 4

# Use PostgreSQL for shared state
pip install psycopg2-binary
export DATABASE_URL=postgresql://user:pass@localhost/ollabridge
ollabridge start --workers 8
```

---

## Troubleshooting

### Diagnostic Command

**First, always run:**
```bash
ollabridge doctor
```

Shows:
```
                     OllaBridge Doctor
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check               ┃ Result                  ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Ollama /api/tags    │ ✅ OK                   │
│ OllaBridge /health  │ ✅ OK                   │
│ API_KEYS configured │ ✅ yes                  │
│ CORS_ORIGINS        │ http://localhost:5173   │
│ Auth usage          │ Use Authorization...    │
└─────────────────────┴─────────────────────────┘
```

### Common Issues

#### "Connection refused"
```bash
# Check if OllaBridge is running
curl http://localhost:11435/health

# If not, start it
ollabridge start
```

#### "Invalid API key"
```bash
# Check your API key
cat .env | grep API_KEYS

# Or generate a new one (starts OllaBridge)
ollabridge start
```

#### "No models available"
```bash
# List available models
ollabridge models --api-key YOUR_KEY

# If empty, Ollama might not be running
# OllaBridge auto-starts it, but you can manually:
ollama serve
```

#### "CORS error" (browser apps)
```bash
# Add your app's URL to .env:
CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# Restart OllaBridge
ollabridge start
```

#### Browser shows "Failed to fetch"
- ✅ Check CORS is configured
- ✅ Make sure you're using correct API key
- ✅ Verify URL: `http://localhost:11435/v1` (note `/v1`)

---

## FAQ

### Is OllaBridge free?
**Yes!** OllaBridge Local is 100% free and open-source. OllaBridge Cloud (multi-user) may have pricing in the future.

### Do I need an internet connection?
**No!** Local mode works 100% offline. Cloud mode requires internet only for pairing and relay.

### Is my data private?
**Yes!** In local mode, data never leaves your devices. In cloud mode, Cloud only relays encrypted messages; it doesn't store your data.

### What models can I use?
Any model supported by Ollama:
- deepseek-r1 (reasoning)
- llama3.1 (general)
- codellama (coding)
- mixtral (large context)
- nomic-embed-text (embeddings)

Full list: https://ollama.ai/library

### Can I use this for commercial projects?
**Yes!** Apache 2.0 license. Use it for anything.

### How is this different from Ollama?
OllaBridge **uses** Ollama but adds:
- Multi-node support
- Load balancing
- OpenAI-compatible API
- Cloud connectivity
- No port forwarding needed

Think: **Ollama = engine, OllaBridge = smart router**

### Can I use GPU acceleration?
**Yes!** If you have NVIDIA GPU, Ollama automatically uses it. No config needed.

### What if I don't have a GPU?
**Works fine on CPU!** Just slower. Or use OllaBridge to connect to a friend's GPU / free cloud GPU.

### How many devices can I connect?
**Unlimited!** Connect as many nodes as you want.

### Can I run multiple gateways?
**Yes!** You can run multiple independent gateways. Each has its own API key.

---

## Next Steps

### Beginner
1. ✅ Install: `pip install ollabridge`
2. ✅ Start: `ollabridge start`
3. ✅ Test: `ollabridge test-chat "Hello"`
4. ✅ Use in your apps!

### Intermediate
1. ✅ Set up LAN access: `ollabridge start --lan`
2. ✅ Add your gaming PC as a node
3. ✅ Configure CORS for browser apps
4. ✅ Try different models

### Advanced
1. ✅ Set up multi-node cluster
2. ✅ Use free cloud GPUs (Colab)
3. ✅ Integrate with LangChain/LlamaIndex
4. ✅ Try OllaBridge Cloud for multi-user

---

## Get Help

- 📖 **Documentation:** https://github.com/ruslanmv/ollabridge
- 🐛 **Report Bug:** https://github.com/ruslanmv/ollabridge/issues
- 💬 **Discussions:** https://github.com/ruslanmv/ollabridge/discussions
- 🎥 **YouTube Tutorial:** [Coming soon]

---

**Made with ❤️ for the local-first AI community**

**Stop paying cloud tokens. Use your own compute.**
