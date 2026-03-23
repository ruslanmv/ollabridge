# OllaBridge Cloud — Relay & Device Management

**Private cloud gateway for routing AI models between your PC and any device.**

---

## Overview

OllaBridge Cloud is the hosted relay component that connects your local GPU to remote clients (Quest VR, web apps, mobile) without port forwarding. Your PC opens a WebSocket tunnel to the cloud; clients connect to the cloud's OpenAI-compatible API.

```
Your PC (GPU)              OllaBridge Cloud            Oculus Quest
┌───────────────┐         ┌──────────────┐         ┌─────────────┐
│ Ollama        │         │              │         │ 3D Avatar   │
│ HomePilot     │◄──WSS──►│  Relay Hub   │◄──HTTPS─│ Chatbot     │
│ OllaBridge    │         │              │         │             │
└───────────────┘         └──────────────┘         └─────────────┘
     Your models              Relay only              Any client
     stay local               (no storage)            connects here
```

**Live instance:** [https://ruslanmv-ollabridge.hf.space](https://ruslanmv-ollabridge.hf.space)

---

## Quick Start

### 1. Create an Account

Visit [https://ruslanmv-ollabridge.hf.space](https://ruslanmv-ollabridge.hf.space) and click **"Get Started Free"** or sign in with Google.

### 2. Pair Your PC

On your local OllaBridge dashboard (`http://localhost:11435`):

1. Click the **Cloud** icon in the sidebar
2. The Cloud URL defaults to `https://ruslanmv-ollabridge.hf.space`
3. Click **"Link to Cloud"**
4. A pairing code appears (e.g., `ABCD-1234`)

### 3. Confirm on Cloud

1. Open the verification URL: `https://ruslanmv-ollabridge.hf.space/link`
2. Log in if not already authenticated
3. Enter the 8-character pairing code
4. Click **"Confirm & Link"**

Your PC auto-connects via WebSocket. Models are discovered and registered automatically.

### 4. Use from Quest VR / Any Client

```bash
# Point your client to the cloud URL
curl -X POST https://ruslanmv-ollabridge.hf.space/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:1.5b","messages":[{"role":"user","content":"Hello!"}]}'
```

---

## Cloud Dashboard

After logging in, the dashboard at `/dashboard` provides an enterprise-grade interface:

### Sidebar Navigation

| Section | Items |
|---------|-------|
| **Navigation** | Overview, Link Device |
| **Devices** | Your paired PCs (with online/offline status) |
| **Resources** | Documentation, API Status, Admin Panel |
| **Settings** | Sign Out |

### Overview Page

- **Server Status** — Gateway, Ollama, Relay node health (polled every 10s)
- **Stats** — Device count, Relay connections, Models available, API endpoint
- **Device Cards** — Each paired PC with name, platform, status, last seen, rename/delete actions
- **Quick Start Guide** — Step-by-step connection instructions

---

## Device Linking Flow

### The `/link` Endpoint

The `/link` page is the verification URL shown to users during the pairing process. It:

1. **Requires authentication** — if not logged in, redirects to `/login?next=/link`
2. **Presents a code entry UI** — 8 auto-advancing input fields with paste support
3. **Validates the code** — checks against active pairing sessions
4. **Confirms the pairing** — links the device to the user's account
5. **Redirects to pair page** — shows the TV-style approval screen

### Pairing Lifecycle

```
PC: POST /device/start
    → Returns: user_code (ABCD-1234), device_code (secret), verification_url, expires_in

User: Opens verification_url (/link)
    → Enters code → POST confirms pairing

PC: POST /device/poll (every 3 seconds)
    → Returns: status=pending → status=approved (with device_token)

PC: Opens WebSocket to /relay/connect (with device_token)
    → Sends: hello + model list
    → Receives: chat/model requests
    → Forwards to local Ollama/HomePilot
    → Returns responses through tunnel
```

### Auto-Connect on Restart

Credentials are saved to `~/.ollabridge/cloud_device.json`. On restart, OllaBridge automatically reconnects to the cloud without re-pairing.

---

## API Reference

### Cloud-Facing Endpoints (for clients like Quest VR)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/models` | List all available models (local + relay) |
| POST | `/v1/chat/completions` | Chat completion (OpenAI-compatible) |
| GET | `/health` | Service health with relay stats |
| GET | `/ollama/status` | Combined Ollama + HomePilot + Relay status |

### Local Admin Endpoints (OllaBridge local → Cloud)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/device/start` | Start pairing flow |
| POST | `/device/confirm` | User confirms code (with X-User-Id) |
| POST | `/device/poll` | PC polls for approval |
| WS | `/relay/connect` | WebSocket relay tunnel (Bearer token auth) |

### Web UI Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Landing page (redirects to `/dashboard` if logged in) |
| GET | `/link` | Device linking code entry page |
| GET | `/login` | Login page (supports `?next=` redirect) |
| GET | `/register` | Registration page |
| GET | `/dashboard` | Enterprise dashboard with sidebar |
| GET | `/pair?code=...` | TV-style pairing approval screen |
| GET | `/docs-page` | Documentation |

---

## Session Management

### Authentication Methods

1. **Email/Password** — Standard registration and login
2. **Google OAuth** — One-click sign-in (auto-registers on first use)
3. **Device Tokens** — HMAC-SHA256 hashed bearer tokens for WebSocket relay

### Session Persistence

- Sessions use secure cookies (SameSite=None, HTTPS-only for HF Spaces iframe support)
- Navigating to `/` (home) automatically redirects to `/dashboard` when logged in
- Login supports `?next=` parameter for post-login redirect (e.g., `/login?next=/link`)
- No need to re-login when navigating between pages

---

## Self-Hosting OllaBridge Cloud

### Prerequisites

- Python 3.10+
- SQLite (development) or PostgreSQL (production)

### Quick Start

```bash
git clone https://github.com/ruslanmv/ollabridge-cloud.git
cd ollabridge-cloud
pip install -e .

# Create .env
cat > .env << 'EOF'
DATABASE_URL=sqlite:///./dev.db
TOKEN_PEPPER=your-random-secret-here
JWT_SECRET=your-jwt-secret-here
VERIFICATION_URL=http://localhost:8000/link
EOF

# Start
python -m ollabridge_cloud.main
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./dev.db` | Database connection string |
| `TOKEN_PEPPER` | `CHANGE_ME_PEPPER` | Secret for hashing tokens |
| `JWT_SECRET` | `CHANGE_ME_JWT_SECRET` | Secret for session cookies |
| `VERIFICATION_URL` | `https://ruslanmv-ollabridge.hf.space/link` | URL shown during pairing |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `GOOGLE_CLIENT_ID` | `` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | `` | Google OAuth client secret |
| `HOMEPILOT_ENABLED` | `false` | Enable HomePilot persona routing |
| `HOMEPILOT_BASE_URL` | `http://localhost:8000` | HomePilot backend URL |
| `FEDERATION_ENABLED` | `false` | Enable peer mesh federation |
| `FEDERATION_PEERS` | `[]` | Comma-separated peer URLs |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Allowed CORS origins |

### Deploy to Hugging Face Spaces

OllaBridge Cloud is designed for HF Spaces deployment:

```bash
# The repo includes a Dockerfile for HF Spaces
# Push to a HF Space and it auto-deploys
```

---

## Security

- **Token Hashing:** HMAC-SHA256 with server-side pepper (no plaintext tokens stored)
- **Password Hashing:** SHA256 with per-user salt
- **Session Cookies:** Secure, HttpOnly, SameSite=None
- **CORS:** Configurable origins for cross-origin clients
- **Privacy:** Cloud relay only routes requests — model weights and data stay on your PC
- **Encrypted Tunnel:** WebSocket connections use WSS (TLS) in production

---

## Troubleshooting

### "Not Found" on /link

Make sure OllaBridge Cloud is running the latest version with the `/link` route.
The endpoint was added to handle device verification. Update and redeploy.

### Session Lost After Navigating to Home

Fixed: The home page (`/`) now redirects to `/dashboard` for logged-in users.
Pull the latest changes and redeploy.

### Pairing Code Expired

Codes expire after 10 minutes. Start a new pairing from the OllaBridge local Cloud tab.

### WebSocket Disconnects

The relay auto-reconnects with exponential backoff (2s, 4s, 8s, 16s, 30s).
Check the Cloud tab in OllaBridge local for connection status and error messages.

### Quest VR Can't Connect

1. Verify the cloud URL is accessible: `curl https://your-cloud.hf.space/health`
2. Check that your PC is connected (Cloud tab shows "Connected")
3. Ensure the model you're requesting is available: `curl https://your-cloud.hf.space/v1/models`

---

## Related Documentation

- [Tutorial — Full OllaBridge Guide](TUTORIAL.md)
- [Architecture — Technical Deep Dive](ARCHITECTURE.md)
- [Examples — Code Samples](EXAMPLES.md)
- [MCP — AI Agent Control](MCP.md)
