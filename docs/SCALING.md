# Distributed Compute, Scaling & Public Access

How to attach more GPUs/nodes, how the dial-out architecture works, scaling options,
and (optional) public exposure. See `docs/ARCHITECTURE.md` for the full design and
`docs/DEPLOYMENT_HARDENING.md` before exposing anything publicly.

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
- Auto-installs Ollama if needed
- Auto-downloads models if needed
- **Dials out** to your gateway (no port forwarding!)
- Shows up as available compute

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
                  Blocked by firewall
                  NAT issues
                  No public IP
```

**OllaBridge (works everywhere):**
```
App → Gateway ← GPU dials in
               Works from anywhere
               No port forwarding
               Ephemeral IPs OK
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

