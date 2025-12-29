# OllaBridge MCP Server

**Model Context Protocol (MCP) support for OllaBridge**

Transform any machine into a local LLM provider through MCP — an AI agent can remotely bootstrap Ollama, pull models, and expose an OpenAI-compatible API endpoint.

---

## 🎯 What is MCP Mode?

MCP mode turns OllaBridge into a **remote-controllable infrastructure layer**. Instead of manually:
1. SSH into a machine
2. Install Ollama
3. Pull models
4. Start the gateway
5. Configure API keys

An **MCP-compatible AI agent** can do all of this through tool calls:

```json
{
  "tool": "ollabridge.install_ollama",
  "arguments": {"assume_yes": true}
}
```

This enables workflows like:
- **"Use my workstation for this task"** — agent connects via MCP, starts Ollama, uses it
- **"Bootstrap 10 dev machines"** — agent parallelizes setup across multiple hosts
- **Self-service AI infrastructure** — developers request compute, agent provisions it

---

## 🚀 Quick Start

### 1. Install OllaBridge

```bash
pip install ollabridge
```

### 2. Start the MCP Server

```bash
ollabridge-mcp
```

The server runs in **stdio mode** (standard JSON-RPC 2.0 over stdin/stdout), which is the standard MCP transport.

### 3. Connect from an MCP Client

**Python example using `mcp` library:**

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="ollabridge-mcp",
    args=[],
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()

        # List available tools
        tools = await session.list_tools()
        print(tools)

        # Check if Ollama is installed
        result = await session.call_tool("ollabridge.check_ollama", {})
        print(result)
```

---

## 🛠️ Available Tools

### `ollabridge.check_ollama`

Check if Ollama is installed on the system.

**Arguments:** None

**Example:**
```json
{
  "tool": "ollabridge.check_ollama",
  "arguments": {}
}
```

**Response:**
```json
{
  "installed": true,
  "message": "Ollama found"
}
```

---

### `ollabridge.install_ollama`

Install Ollama automatically (Linux/macOS).

**Arguments:**
- `assume_yes` (boolean, required): Must be `true` for non-interactive mode

**Example:**
```json
{
  "tool": "ollabridge.install_ollama",
  "arguments": {"assume_yes": true}
}
```

**Response:**
```json
{
  "ok": true,
  "message": "Ollama installation triggered. Verify with ollabridge.check_ollama."
}
```

**⚠️ Security Note:** This runs a system-level installer. Only allow trusted agents to call this tool.

---

### `ollabridge.list_models`

List all installed Ollama models.

**Arguments:** None

**Example:**
```json
{
  "tool": "ollabridge.list_models",
  "arguments": {}
}
```

**Response:**
```json
{
  "ok": true,
  "output": "NAME                    SIZE    \ndeepseek-r1:latest      5.2 GB  \nllama3.1:latest         4.7 GB  \n",
  "message": "Models listed successfully."
}
```

---

### `ollabridge.ensure_model`

Ensure a model is available (pulls if missing).

**Arguments:**
- `model` (string, required): Model name (e.g., `deepseek-r1`, `llama3.1`, `nomic-embed-text`)

**Example:**
```json
{
  "tool": "ollabridge.ensure_model",
  "arguments": {"model": "deepseek-r1"}
}
```

**Response:**
```json
{
  "ok": true,
  "model": "deepseek-r1",
  "message": "Model 'deepseek-r1' is ready."
}
```

**Note:** This may take several minutes for large models.

---

### `ollabridge.start_gateway`

Start the OllaBridge OpenAI-compatible gateway as a background process.

**Arguments:**
- `host` (string, optional): Bind host (default: `127.0.0.1`)
- `port` (integer, optional): Bind port (default: `11435`)
- `model` (string, optional): Default chat model (default: `deepseek-r1`)
- `workers` (integer, optional): Number of workers (default: `1`)
- `share` (boolean, optional): Enable public URL via tunnel (default: `false`)

**Example:**
```json
{
  "tool": "ollabridge.start_gateway",
  "arguments": {
    "host": "127.0.0.1",
    "port": 11435,
    "model": "deepseek-r1",
    "workers": 2
  }
}
```

**Response:**
```json
{
  "ok": true,
  "pid": 12345,
  "base_url": "http://127.0.0.1:11435",
  "openai_base_url": "http://127.0.0.1:11435/v1",
  "health_url": "http://127.0.0.1:11435/health",
  "model": "deepseek-r1",
  "workers": 2,
  "message": "Gateway started. Use ollabridge.health to verify readiness (may take a few seconds)."
}
```

**Important:** Save the `pid` to stop the gateway later.

---

### `ollabridge.stop_gateway`

Stop a running gateway process.

**Arguments:**
- `pid` (integer, required): Process ID from `start_gateway`

**Example:**
```json
{
  "tool": "ollabridge.stop_gateway",
  "arguments": {"pid": 12345}
}
```

**Response:**
```json
{
  "ok": true,
  "pid": 12345,
  "message": "Gateway stopped."
}
```

---

### `ollabridge.health`

Check if the gateway is healthy and ready to accept requests.

**Arguments:**
- `base_url` (string, required): Gateway base URL (from `start_gateway`)

**Example:**
```json
{
  "tool": "ollabridge.health",
  "arguments": {"base_url": "http://127.0.0.1:11435"}
}
```

**Response:**
```json
{
  "ok": true,
  "status_code": 200,
  "response": {
    "status": "healthy",
    "ollama_available": true,
    "version": "1.0.0"
  },
  "message": "Gateway is healthy"
}
```

---

## 📋 Complete Workflow Example

Here's a complete agent workflow to bootstrap a machine into an LLM provider:

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def bootstrap_ollama_provider():
    server_params = StdioServerParameters(command="ollabridge-mcp", args=[])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Step 1: Check if Ollama is installed
            result = await session.call_tool("ollabridge.check_ollama", {})
            print("Check Ollama:", result)

            # Step 2: Install if missing
            if not result["installed"]:
                install = await session.call_tool(
                    "ollabridge.install_ollama",
                    {"assume_yes": True}
                )
                print("Install Ollama:", install)

            # Step 3: Ensure model is available
            model = await session.call_tool(
                "ollabridge.ensure_model",
                {"model": "deepseek-r1"}
            )
            print("Ensure Model:", model)

            # Step 4: Start gateway
            gateway = await session.call_tool(
                "ollabridge.start_gateway",
                {
                    "host": "127.0.0.1",
                    "port": 11435,
                    "model": "deepseek-r1",
                    "workers": 1
                }
            )
            print("Gateway Started:", gateway)

            # Step 5: Wait a moment for startup
            await asyncio.sleep(3)

            # Step 6: Check health
            health = await session.call_tool(
                "ollabridge.health",
                {"base_url": gateway["base_url"]}
            )
            print("Health Check:", health)

            # Step 7: Use the gateway
            print("\nGateway is ready!")
            print(f"Use this as your OpenAI base_url: {gateway['openai_base_url']}")
            print("Check .env file for API key")

            # Save PID for cleanup
            return gateway["pid"]

asyncio.run(bootstrap_ollama_provider())
```

---

## 🔐 Security Considerations

**MCP mode exposes powerful system-level operations.** Follow these guidelines:

### 1. Run Locally Only (Default)

By default, MCP server uses **stdio transport** (stdin/stdout), which means:
- ✅ The agent must have local shell access
- ✅ No network exposure
- ✅ Inherits user permissions

### 2. Restrict Tool Access (Future)

Future versions will support:
- **Tool allowlists** — only specific tools enabled
- **Interactive approval** — human confirms dangerous operations
- **Rate limiting** — prevent abuse
- **Audit logging** — track all tool calls

### 3. Don't Expose Over Network (Yet)

Current version is **stdio-only**. Do NOT expose MCP server over HTTP/WebSocket without:
- Strong authentication
- Encryption (TLS)
- Access controls
- Rate limiting

### 4. Trust Your Agent

Only connect MCP clients you trust. A malicious agent could:
- Install software
- Pull large models (disk usage)
- Start processes
- Access local files (through normal OllaBridge operations)

---

## 🏗️ Architecture

```
┌─────────────────┐
│   AI Agent      │
│  (MCP Client)   │
└────────┬────────┘
         │ JSON-RPC 2.0
         │ (stdio)
┌────────▼────────┐
│ ollabridge-mcp  │
│  MCP Server     │
└────────┬────────┘
         │
         ├─► install_ollama()
         ├─► ensure_model()
         └─► start_gateway()
                   │
         ┌─────────▼─────────┐
         │  OllaBridge API   │
         │   (FastAPI)       │
         └─────────┬─────────┘
                   │
         ┌─────────▼─────────┐
         │    Ollama         │
         │  (Local Models)   │
         └───────────────────┘
```

### Key Design Decisions

1. **Stdio Transport** — Simple, secure, standard MCP protocol
2. **Background Gateway** — MCP server spawns gateway as subprocess (stays responsive)
3. **Non-Interactive Mode** — All installer prompts require `assume_yes=true`
4. **Stateless Tools** — Each tool call is independent (no session state)

---

## 🔮 Roadmap

Future MCP features:

- [ ] **HTTP/SSE transport** (for remote agents)
- [ ] **Tool allowlists** (security profiles)
- [ ] **Interactive approval** (human-in-the-loop for dangerous ops)
- [ ] **Resource limits** (max disk usage, max models, rate limits)
- [ ] **Multi-tenant support** (multiple agents, isolated environments)
- [ ] **Provider profiles** (save/load gateway configs)
- [ ] **Audit logging** (all tool calls logged with agent identity)
- [ ] **Streaming support** (real-time model pull progress)

---

## 📚 Resources

- **MCP Specification:** https://modelcontextprotocol.io/
- **OllaBridge Docs:** https://github.com/ruslanmv/ollabridge
- **Ollama Docs:** https://ollama.ai/

---

## ❓ FAQ

### Can I use MCP mode for production?

MCP mode is **beta**. It's safe for:
- ✅ Local development machines
- ✅ Trusted internal networks
- ✅ Single-user workstations

It's **NOT** ready for:
- ❌ Multi-tenant SaaS
- ❌ Public internet exposure
- ❌ Untrusted agents

### Does MCP mode replace the regular CLI?

No! MCP mode is **optional** and **additive**:
- `ollabridge start` — Regular interactive mode (default)
- `ollabridge-mcp` — MCP server mode (for agents)

Both modes use the same core code.

### How do I debug MCP tool calls?

MCP uses JSON-RPC 2.0 over stdio. To see the protocol:

```bash
ollabridge-mcp 2>&1 | tee mcp.log
```

Then send JSON messages manually:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | ollabridge-mcp
```

### What if installation fails?

If `ollabridge.install_ollama` fails:
1. Check the error message in the response
2. Install Ollama manually: https://ollama.com/download
3. Verify: `ollabridge.check_ollama`

### Can I run multiple gateways?

Yes! Each `start_gateway` call uses a different port:

```json
{"tool": "ollabridge.start_gateway", "arguments": {"port": 11435}}
{"tool": "ollabridge.start_gateway", "arguments": {"port": 11436}}
```

Track the `pid` for each to stop them individually.

---

**Questions?** Open an issue: https://github.com/ruslanmv/ollabridge/issues
