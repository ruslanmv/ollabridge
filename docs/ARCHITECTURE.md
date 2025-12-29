# 🏗️ OllaBridge Architecture

**Understanding how OllaBridge works under the hood**

---

## Overview

OllaBridge uses a **Control Plane + Node Agent** architecture where:
- **Control Plane (Gateway)**: Your apps connect here
- **Nodes**: Machines running LLMs (local, remote, cloud)
- **Connectors**: Transport layer between gateway and nodes

**Key Innovation:** Nodes **dial out** to the gateway, eliminating port forwarding and firewall issues.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Your Applications                     │
│    (Python, Node.js, Browser, CLI, LangChain, etc.)    │
└────────────────┬────────────────────────────────────────┘
                 │
                 │ HTTP/HTTPS
                 │ OpenAI API Format
                 │
┌────────────────▼────────────────────────────────────────┐
│              OllaBridge Control Plane                    │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Registry   │  │    Router    │  │  Relay Hub   │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │         API Endpoints                             │  │
│  │  /v1/chat/completions                            │  │
│  │  /v1/embeddings                                   │  │
│  │  /v1/models                                       │  │
│  │  /admin/runtimes                                  │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────┬─────────────┬─────────────┬──────────────┘
              │             │             │
              │             │             │
    ┌─────────▼─────┐ ┌─────▼─────┐ ┌───▼──────┐
    │ Local Ollama  │ │ Remote GPU│ │ Cloud GPU│
    │ (Built-in)    │ │ (RelayLink│ │(RelayLink│
    │               │ │ dials out)│ │dials out)│
    └───────────────┘ └───────────┘ └──────────┘
```

---

## Core Components

### 1. Control Plane (Gateway)

**Location:** `src/ollabridge/api/main.py`

The control plane is the single entrypoint for all your applications.

**Responsibilities:**
- Accept OpenAI-compatible requests
- Authenticate requests (API keys)
- Route requests to appropriate nodes
- Aggregate responses
- Log all requests for audit

**Key Features:**
- FastAPI async web framework
- Rate limiting per API key
- CORS support for browser apps
- Health checks
- Admin endpoints

### 2. Runtime Registry

**Location:** `src/ollabridge/core/registry.py`

An in-memory store of all connected nodes.

**What It Tracks:**
```python
@dataclass
class RuntimeNodeState:
    node_id: str              # Unique identifier
    connector: str            # relay_link | direct_endpoint | local_ollama
    endpoint: str | None      # HTTP endpoint (if applicable)
    tags: list[str]           # For routing rules
    models: list[str]         # Available models
    capacity: int             # Concurrent request capacity
    healthy: bool             # Health status
    last_seen: datetime       # Last heartbeat
```

**Operations:**
- `upsert(node)`: Register or update a node
- `touch(node_id)`: Update last_seen timestamp
- `remove(node_id)`: Remove a node
- `list()`: Get all nodes

### 3. Router

**Location:** `src/ollabridge/core/router.py`

Decides which node handles each request.

**Current Strategy:**
- Round-robin across healthy nodes
- Respects model availability (optional)

**Future Strategies:**
- Tag-based routing (e.g., "coding" → GPU nodes)
- Latency-aware selection
- Weighted load balancing
- Model-specific pinning

**Code Example:**
```python
async def choose_node(self, *, model: str | None = None) -> RouteDecision:
    nodes = [n for n in await self.registry.list() if n.healthy]
    if not nodes:
        raise RuntimeError("no healthy runtimes available")

    # Round-robin
    idx = self._rr_counter % len(nodes)
    self._rr_counter += 1
    return RouteDecision(node=nodes[idx])
```

### 4. Relay Hub

**Location:** `src/ollabridge/api/relay.py`

Manages WebSocket connections from nodes.

**Protocol:**
```json
// Node → Server: Hello
{
  "type": "hello",
  "node_id": "colab-gpu-1",
  "tags": ["gpu", "free"],
  "models": ["deepseek-r1"],
  "capacity": 1
}

// Server → Node: Request
{
  "type": "req",
  "id": "req-123",
  "op": "chat",
  "payload": {
    "model": "deepseek-r1",
    "messages": [...]
  }
}

// Node → Server: Response
{
  "type": "res",
  "id": "req-123",
  "ok": true,
  "data": {
    "content": "Hello! How can I help?"
  }
}
```

**Multiplexing:**
- Multiple requests can be in-flight
- Each request has a unique ID
- Responses matched by ID
- Timeouts handled gracefully

---

## Connector Types

### 1. RelayLink (Default)

**Location:** `src/ollabridge/api/relay.py`

**How It Works:**
```
1. Node dials OUT to gateway via WebSocket
2. Gateway keeps connection open
3. When request arrives, gateway sends it over WebSocket
4. Node processes it and sends response back
5. Gateway returns response to app
```

**Advantages:**
- ✅ Works everywhere (no inbound ports needed)
- ✅ Survives IP changes
- ✅ NAT/firewall friendly
- ✅ Perfect for ephemeral/free compute

**Trade-offs:**
- Slightly higher latency than DirectEndpoint
- Requires persistent connection

**Use Cases:**
- Free GPU clouds (Colab, Kaggle)
- Laptops on WiFi
- Nodes behind corporate firewalls

### 2. DirectEndpoint

**Location:** `src/ollabridge/connectors/direct_endpoint.py`

**How It Works:**
```
1. Node has stable IP/hostname
2. Gateway makes HTTP requests directly to node
3. Lowest latency
```

**Advantages:**
- ✅ Best performance
- ✅ Simple HTTP calls
- ✅ Stateless

**Requirements:**
- Node must be reachable from gateway
- Node runs a simple HTTP server

**Use Cases:**
- Production servers
- Internal network nodes
- Cloud VMs with static IPs

### 3. LocalOllama

**Location:** Built-in to `src/ollabridge/api/main.py`

**How It Works:**
```
1. Gateway detects local Ollama installation
2. Calls it directly via built-in client
3. Zero-config for single-machine setup
```

**Advantages:**
- ✅ Zero configuration
- ✅ Great for development
- ✅ Lowest latency (same machine)

**Use Cases:**
- Development
- Single-machine deployments
- Quick prototyping

---

## Request Flow

### Scenario: Chat Request from Python App

```
1. App sends POST to /v1/chat/completions
   │
   ├─> Gateway validates API key
   │
   ├─> Gateway calls Router.choose_node()
   │   │
   │   └─> Router picks best node (round-robin)
   │
   ├─> Gateway checks node connector type
   │
   ├─> If RelayLink:
   │   │
   │   ├─> Gateway sends request via WebSocket
   │   │
   │   ├─> Node receives it, processes locally
   │   │
   │   └─> Node sends response via WebSocket
   │
   ├─> If DirectEndpoint:
   │   │
   │   ├─> Gateway makes HTTP POST to node
   │   │
   │   └─> Node returns response
   │
   ├─> If LocalOllama:
   │   │
   │   └─> Gateway calls local Ollama directly
   │
   ├─> Gateway logs request to database
   │
   └─> Gateway returns response to app
```

---

## Security Model

### API Key Authentication

**Location:** `src/ollabridge/core/security.py`

```python
async def require_api_key(
    key: str = Depends(get_api_key_header)
) -> str:
    valid_keys = [k.strip() for k in settings.API_KEYS.split(",")]
    if key not in valid_keys:
        raise HTTPException(401, "Invalid API key")
    return key
```

**Supported Formats:**
- `Authorization: Bearer <key>`
- `X-API-Key: <key>`

### Enrollment Tokens

**Location:** `src/ollabridge/core/enrollment.py`

Used for secure node registration.

**Properties:**
- Short-lived (default: 1 hour)
- Cryptographically signed
- One-time use (optional)

**Flow:**
```
1. Admin creates token: ollabridge enroll-create
2. Admin shares token with node operator
3. Node uses token to join: ollabridge-node join --token ...
4. Token expires after TTL
```

### Rate Limiting

**Location:** `src/ollabridge/api/main.py`

```python
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT]
)
```

Default: 60 requests/minute per IP

---

## Database Schema

### RuntimeNode (Persistent)

```sql
CREATE TABLE runtimenode (
    id INTEGER PRIMARY KEY,
    node_id VARCHAR UNIQUE,
    connector VARCHAR,
    endpoint VARCHAR,
    tags VARCHAR,  -- CSV
    models VARCHAR,  -- CSV
    capacity INTEGER,
    last_seen TIMESTAMP,
    healthy BOOLEAN
);
```

**Use:** Persist node metadata across restarts

### RequestLog (Audit Trail)

```sql
CREATE TABLE requestlog (
    id INTEGER PRIMARY KEY,
    ts TIMESTAMP,
    path VARCHAR,
    model VARCHAR,
    latency_ms INTEGER,
    ok BOOLEAN,
    client VARCHAR
);
```

**Use:** Audit, analytics, debugging

### ModelRoute (Routing Rules)

```sql
CREATE TABLE modelroute (
    id INTEGER PRIMARY KEY,
    model_pattern VARCHAR,
    selector VARCHAR,  -- e.g., "tag:gpu"
    priority INTEGER
);
```

**Use:** Advanced routing policies (future feature)

---

## Node Agent

**Location:** `src/ollabridge/node/`

The node agent runs on any machine with GPUs/CPUs.

### Components

**1. Agent (`agent.py`)**
- Connects to control plane
- Maintains WebSocket connection
- Processes requests
- Sends heartbeats

**2. Runtime Adapter (`runtime.py`)**
- Abstracts local LLM runtime (Ollama, vLLM, etc.)
- Provides unified interface

**3. CLI (`cli.py`)**
- Simple join command
- Auto-detects and installs dependencies

### Node Lifecycle

```
1. Start: ollabridge-node join --control ... --token ...
   │
   ├─> Check if Ollama installed (install if needed)
   │
   ├─> Check if model exists (pull if needed)
   │
   ├─> Connect to control plane via WebSocket
   │
   ├─> Send hello message
   │
   ├─> Receive hello_ack
   │
   ├─> Enter request-response loop
   │   │
   │   ├─> Receive request
   │   │
   │   ├─> Process locally (call Ollama)
   │   │
   │   └─> Send response
   │
   └─> On disconnect: cleanup
```

---

## Configuration

### Environment Variables

**Gateway:**
```env
# Server
HOST=0.0.0.0
PORT=11435

# Security
API_KEYS=key1,key2
ENROLLMENT_SECRET=secret-for-signing-tokens
ENROLLMENT_TTL_SECONDS=3600

# Features
MODE=gateway
RELAY_ENABLED=true
LOCAL_RUNTIME_ENABLED=true

# Models
DEFAULT_MODEL=deepseek-r1
DEFAULT_EMBED_MODEL=nomic-embed-text

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
```

**Node:**
```env
OBRIDGE_NODE_ID=my-gpu-node
OBRIDGE_PUBLIC_LINK_CMD=ngrok
```

---

## Scalability

### Vertical Scaling

```bash
# Add more workers (shared-nothing processes)
ollabridge start --workers 8
```

Each worker:
- Handles requests independently
- Shares the relay hub via in-memory state
- Uses round-robin for fairness

### Horizontal Scaling

**Option 1: Multiple Gateways**
```
Load Balancer
    ├─> Gateway 1
    ├─> Gateway 2
    └─> Gateway 3
```

Each gateway has its own node connections.

**Option 2: Shared Registry (Future)**
- Use Redis for shared registry
- All gateways see all nodes
- True horizontal scaling

### Database Scaling

**Development:** SQLite (automatic)

**Production:**
```bash
export DATABASE_URL=postgresql://user:pass@localhost/ollabridge
```

PostgreSQL handles:
- Connection pooling
- Replication
- Sharding (if needed)

---

## Monitoring

### Health Endpoint

```bash
curl http://localhost:11435/health
```

**Response:**
```json
{
  "status": "ok",
  "mode": "gateway",
  "default_model": "deepseek-r1",
  "detail": "runtimes=3"
}
```

### Runtime Status

```bash
curl -H "X-API-Key: key" http://localhost:11435/admin/runtimes
```

Shows all connected nodes + health status.

### Request Logs

```bash
curl -H "X-API-Key: key" http://localhost:11435/admin/recent
```

Last 200 requests with latency, model, status.

---

## Future Enhancements

### Planned Features

**1. Streaming Support**
- WebSocket or SSE for streaming responses
- Compatible with OpenAI streaming API

**2. Tag-Based Routing**
```python
# Route "coding" requests to GPU nodes
@app.post("/v1/chat/completions")
async def chat(req: ChatReq, tags: list[str] = ["coding"]):
    decision = await router.choose_node(tags=tags)
    ...
```

**3. Model-Specific Routes**
```yaml
routes:
  - model: "llama-70b"
    nodes: ["big-gpu-1", "big-gpu-2"]
  - model: "deepseek-r1"
    nodes: ["any"]
```

**4. Metrics & Observability**
- Prometheus `/metrics` endpoint
- OpenTelemetry tracing
- Grafana dashboards

**5. Web UI**
- Visual node management
- Real-time monitoring
- Configuration interface

---

## Performance Characteristics

### Latency

**LocalOllama:**
- Base latency: ~5ms (same machine)
- Best for: Development, single-node

**DirectEndpoint:**
- Base latency: ~10-50ms (network RTT)
- Best for: Production nodes with static IPs

**RelayLink:**
- Base latency: ~20-100ms (WebSocket overhead)
- Best for: Ephemeral/mobile nodes

### Throughput

**Gateway:**
- ~1000 req/s per worker (no rate limit)
- Scales linearly with workers

**Node:**
- Limited by model inference time
- Typical: 10-100 tokens/s
- Use multiple nodes for higher throughput

---

## Developer Guide

### Adding a New Connector

1. Create `src/ollabridge/connectors/my_connector.py`
2. Implement `Connector` interface
3. Register in router logic
4. Add tests

**Example:**
```python
from ollabridge.connectors.base import Connector

class MyConnector(Connector):
    async def chat(self, *, base: str, payload: dict) -> dict:
        # Your transport logic here
        ...

    async def embeddings(self, *, base: str, payload: dict) -> dict:
        ...
```

### Adding a Runtime Adapter

1. Create `src/ollabridge/node/runtimes/my_runtime.py`
2. Implement adapter interface
3. Update node agent to detect it

---

## FAQ

**Q: Why WebSocket instead of HTTP polling?**
A: WebSocket allows nodes to dial out once and maintain a persistent connection. HTTP polling would require nodes to repeatedly connect, wasting resources.

**Q: Can I use OllaBridge without nodes?**
A: Yes! LocalOllama mode works out-of-the-box if you have Ollama installed locally.

**Q: How does routing work with multiple models?**
A: Currently round-robin. Future versions will support model-specific and tag-based routing.

**Q: Is there a limit to how many nodes I can connect?**
A: No hard limit. Tested with 100+ nodes. Limited by gateway resources (memory, connections).

**Q: Can nodes connect from behind NAT/firewall?**
A: Yes! That's the whole point of RelayLink. Nodes dial OUT, so no inbound ports needed.

---

## Further Reading

- [Quick Start Guide](QUICKSTART.md)
- [Code Examples](EXAMPLES.md)
- [Main README](../README.md)

---

**Questions?** [Open an issue](https://github.com/ruslanmv/ollabridge/issues) or [start a discussion](https://github.com/ruslanmv/ollabridge/discussions)!
