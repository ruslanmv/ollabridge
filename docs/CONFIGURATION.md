# Configuration & Authentication

Environment variables, API keys, auth modes, and enrollment tokens for the local gateway.
Moved from the README; see also `docs/SECURITY.md` and `docs/DEPLOYMENT_HARDENING.md`.

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

