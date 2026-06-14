# CLI Reference & Beginner Guide

Every `ollabridge` and `ollabridge-node` command, a step-by-step beginner walkthrough,
and optional cloud pairing from the CLI. See also `docs/RELAY_VERIFICATION.md`.

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
│ Ollama /api/tags    │ OK                           │
│ OllaBridge /health  │ OK                           │
│ API_KEYS configured │ yes                          │
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

OllaBridge Local can **optionally** connect to **[OllaBridge Cloud](https://ruslanmv-ollabridge.hf.space)** for multi-user, multi-device deployments.

<p align="center">
  <img src="assets/diagrams/architecture.svg" alt="OllaBridge end-to-end architecture: local gateway, Providers Hub, Hugging Face Inference Providers, and OllaBridge Cloud" width="100%" />
</p>

### Cloud Features

- 🔐 **TV-style device pairing** with ABCD-1234 codes
- 👥 **Multi-user support** with email/password or Google OAuth
- 🌍 **No port forwarding needed** (devices dial out via WebSocket)
- 📱 **Multi-device per user** (PC + Quest + phone, etc.)
- 🔄 **Streaming support** for real-time responses
- 🏢 **Enterprise dashboard** with sidebar layout, device management, server monitoring
- 🤝 **HomePilot personas** routed through the cloud relay
- 🔗 **Federation** for peer mesh across multiple cloud instances

**Cloud Relay UI**: The OllaBridge dashboard includes a **Cloud** tab — click "Link to Cloud", enter the pairing code on the [Cloud dashboard](https://ruslanmv-ollabridge.hf.space/link), and your PC's GPU is instantly available to Quest VR headsets through an encrypted WebSocket tunnel.

### Pairing Your Device with Cloud

#### Option A: From Dashboard (Recommended)

1. Open OllaBridge dashboard → Click **Cloud** in sidebar
2. Click **"Link to Cloud"** (defaults to `https://ruslanmv-ollabridge.hf.space`)
3. A pairing code appears (e.g., `ABCD-1234`)
4. Open `https://ruslanmv-ollabridge.hf.space/link` → enter the code → confirm

#### Option B: From CLI

```bash
# 1. Pair this device with OllaBridge Cloud
ollabridge-node cloud-pair --cloud https://ruslanmv-ollabridge.hf.space

# Shows pairing code - approve at /link on the Cloud dashboard

# 2. Connect to Cloud (uses saved credentials)
ollabridge-node cloud-connect
```

**How it works:**
1. `cloud-pair` gets a pairing code from Cloud (`/device/start`)
2. You approve the code at `/link` on the Cloud web UI
3. Device credentials saved to `~/.ollabridge/cloud_device.json`
4. WebSocket tunnel opens to `/relay/connect` — models registered automatically
5. Cloud routes client requests to your device through the tunnel

### Local Mode (Default) vs Cloud Mode

| Feature | Local Mode | Cloud Mode |
|---------|------------|------------|
| **Setup** | `ollabridge-node join --control <gateway> --token <token>` | Dashboard Cloud tab or `cloud-pair` CLI |
| **Authentication** | Enrollment token | TV-style device pairing + user accounts |
| **Users** | Single self-hosted | Multi-user with Google OAuth |
| **Devices** | Manual node management | Per-user device ownership with dashboard |
| **Dashboard** | Local React UI | Enterprise sidebar with device monitoring |
| **Port forwarding** | Not needed (outbound) | Not needed (WebSocket relay) |

**Both modes work together!** Run local gateway + nodes for self-hosting, and optionally pair devices with Cloud for multi-user scenarios.

> **Full Cloud documentation:** [docs/CLOUD.md](docs/CLOUD.md)

---

