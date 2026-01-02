# OllaBridge Demo Client

> **A simple, beautiful web client demonstrating how to integrate with OllaBridge in just 2 clicks!**

This demo showcases the **easiest way** to connect any web application to your local OllaBridge instance, enabling you to use local LLMs with an OpenAI-compatible API.

[![OllaBridge](https://img.shields.io/badge/OllaBridge-Compatible-blue)](https://github.com/ruslanmv/ollabridge)
[![License](https://img.shields.io/badge/license-MIT-green)](../LICENSE)

---

## 🎯 What's This For?

This example demonstrates:

✅ **2-Click Setup** - Install OllaBridge, connect from browser
✅ **Real Integration** - Actual API calls to OllaBridge endpoints
✅ **OpenAI Compatibility** - Uses standard `/v1/chat/completions` endpoint
✅ **Authentication** - Proper API key handling with Bearer token
✅ **CORS Configuration** - Production-ready cross-origin setup
✅ **Best Practices** - Clean code structure for your own projects

---

## 🚀 Quick Start (2 Clicks!)

### **Click 1: Install OllaBridge**

Choose your platform:

#### **Mac/Linux:**
```bash
cd ..  # Go to project root
./example/install-ollabridge.sh
```

#### **Windows (PowerShell):**
```powershell
cd ..  # Go to project root
.\example\install-ollabridge.ps1
```

#### **Or install manually:**
```bash
pip install ollabridge
ollabridge start
```

---

### **Click 2: Connect from Browser**

1. **Serve the demo client:**
   ```bash
   cd example
   python3 -m http.server 3000
   ```

   > ⚠️ **Important:** Serve from `http://localhost:3000` to match CORS settings!

2. **Open in browser:**
   ```
   http://localhost:3000
   ```

3. **Enter connection details:**
   - **Server URL:** `http://localhost:11435`
   - **API Key:** `dev-key-change-me` (or your custom key from `.env`)

4. **Click "Connect"** and start chatting!

---

## 📋 Prerequisites

Before you begin, ensure you have:

- ✅ **Python 3.8+** installed
- ✅ **Ollama** installed and running ([Download here](https://ollama.ai))
- ✅ **At least one model** pulled in Ollama:
  ```bash
  ollama pull deepseek-r1
  # or
  ollama pull llama3
  # or any other model
  ```

---

## 🏗️ How It Works

### Architecture Overview

```
┌─────────────────┐      ┌──────────────┐      ┌─────────────┐
│  Browser Client │ ───> │  OllaBridge  │ ───> │   Ollama    │
│  (index.html)   │ <─── │  (Gateway)   │ <─── │  (Backend)  │
└─────────────────┘      └──────────────┘      └─────────────┘
     HTTP/CORS          OpenAI-compatible        Local Models
```

### API Flow

1. **Health Check** (no auth required)
   ```http
   GET http://localhost:11435/health
   ```

2. **Load Models** (requires API key)
   ```http
   GET http://localhost:11435/v1/models
   Authorization: Bearer dev-key-change-me
   ```

3. **Send Chat Request** (requires API key)
   ```http
   POST http://localhost:11435/v1/chat/completions
   Authorization: Bearer dev-key-change-me
   Content-Type: application/json

   {
     "model": "deepseek-r1",
     "messages": [{"role": "user", "content": "Hello!"}]
   }
   ```

---

## 🔧 Configuration

### OllaBridge Configuration (`.env`)

Create a `.env` file in your project root:

```env
# Server Settings
HOST=0.0.0.0
PORT=11435

# Authentication
API_KEYS=dev-key-change-me,another-key

# CORS (CRITICAL for web clients!)
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# Ollama Backend
OLLAMA_BASE_URL=http://localhost:11434

# Default Model
DEFAULT_MODEL=deepseek-r1
```

### Key Configuration Notes

| Setting | Purpose | Example |
|---------|---------|---------|
| `API_KEYS` | Comma-separated list of valid API keys | `key1,key2,key3` |
| `CORS_ORIGINS` | Allowed origins for browser requests | `http://localhost:3000` |
| `DEFAULT_MODEL` | Fallback model if client doesn't specify | `deepseek-r1` |
| `OLLAMA_BASE_URL` | Where OllaBridge finds Ollama | `http://localhost:11434` |

---

## 💡 Best Practices for Client Development

### 1. **Authentication**

Always use the `Authorization` header with Bearer token:

```javascript
const headers = {
  'Authorization': `Bearer ${apiKey}`,
  'Content-Type': 'application/json'
};

const response = await fetch(`${baseUrl}/v1/chat/completions`, {
  method: 'POST',
  headers: headers,
  body: JSON.stringify({
    model: 'deepseek-r1',
    messages: [{ role: 'user', content: 'Hello!' }]
  })
});
```

### 2. **CORS Handling**

**For Development:**
- Serve your client from `http://localhost:3000` (or any port you configured)
- Add your origin to `CORS_ORIGINS` in OllaBridge `.env`

**For Production:**
- Add your production domain to `CORS_ORIGINS`
- Example: `CORS_ORIGINS=https://myapp.com,https://www.myapp.com`

### 3. **Error Handling**

Always handle common errors gracefully:

```javascript
try {
  const response = await fetch(url, options);
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Request failed');
  }
  return await response.json();
} catch (err) {
  console.error('API Error:', err.message);
  // Show user-friendly error message
}
```

### 4. **Model Selection**

Load available models dynamically:

```javascript
async function loadModels() {
  const response = await fetch(`${baseUrl}/v1/models`, {
    headers: { 'Authorization': `Bearer ${apiKey}` }
  });
  const data = await response.json();
  return data.data; // Array of {id: "model-name", object: "model"}
}
```

### 5. **Streaming Support**

For real-time responses, use streaming:

```javascript
const response = await fetch(`${baseUrl}/v1/chat/completions`, {
  method: 'POST',
  headers: headers,
  body: JSON.stringify({
    model: 'deepseek-r1',
    messages: messages,
    stream: true  // Enable streaming
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const {done, value} = await reader.read();
  if (done) break;

  const chunk = decoder.decode(value);
  // Process SSE chunks
  console.log(chunk);
}
```

---

## 🧪 Testing

### Using the Makefile

We provide a convenient Makefile for testing:

```bash
# Install OllaBridge
make install

# Run the demo client
make run

# Run both in one command
make test
```

### Manual Testing

1. **Test OllaBridge is running:**
   ```bash
   curl http://localhost:11435/health
   ```

2. **Test authentication:**
   ```bash
   curl http://localhost:11435/v1/models \
     -H "Authorization: Bearer dev-key-change-me"
   ```

3. **Test chat completion:**
   ```bash
   curl http://localhost:11435/v1/chat/completions \
     -H "Authorization: Bearer dev-key-change-me" \
     -H "Content-Type: application/json" \
     -d '{
       "model": "deepseek-r1",
       "messages": [{"role": "user", "content": "Hello!"}]
     }'
   ```

---

## 🔒 Security Considerations

### Development vs Production

| Environment | Recommendations |
|-------------|-----------------|
| **Development** | Use simple keys like `dev-key-change-me` for testing |
| **Production** | Use strong, random API keys (32+ characters) |

### Generate Secure API Keys

```bash
# Linux/Mac
openssl rand -hex 32

# Python
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Network Security

- **Development:** Run on `localhost` only
- **Production:** Use HTTPS, configure firewall rules, use reverse proxy (nginx/Caddy)

---

## 📁 Project Structure

```
example/
├── index.html                 # Main demo client
├── install-ollabridge.sh      # Mac/Linux installer
├── install-ollabridge.ps1     # Windows installer
├── Makefile                   # Testing commands
├── .env.example               # Configuration template
└── README.md                  # This file
```

---

## 🌐 Integration Examples

### Python Client

```python
import requests

base_url = "http://localhost:11435"
api_key = "dev-key-change-me"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

response = requests.post(
    f"{base_url}/v1/chat/completions",
    headers=headers,
    json={
        "model": "deepseek-r1",
        "messages": [{"role": "user", "content": "Hello!"}]
    }
)

print(response.json())
```

### JavaScript/Node.js Client

```javascript
const fetch = require('node-fetch');

const baseUrl = 'http://localhost:11435';
const apiKey = 'dev-key-change-me';

async function chat(prompt) {
  const response = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model: 'deepseek-r1',
      messages: [{ role: 'user', content: prompt }]
    })
  });

  return await response.json();
}

chat('Hello!').then(console.log);
```

### cURL Client

```bash
curl http://localhost:11435/v1/chat/completions \
  -H "Authorization: Bearer dev-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-r1",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

---

## 🐛 Troubleshooting

### Common Issues

#### 1. **CORS Error in Browser**

**Problem:** `Access to fetch has been blocked by CORS policy`

**Solution:**
- Ensure you're serving from `http://localhost:3000`
- Check `CORS_ORIGINS` in OllaBridge `.env` includes your origin
- Restart OllaBridge after changing `.env`

#### 2. **Connection Refused**

**Problem:** `Failed to fetch` or connection errors

**Solution:**
- Verify OllaBridge is running: `curl http://localhost:11435/health`
- Check the port matches (default: 11435)
- Ensure no firewall is blocking the connection

#### 3. **401 Unauthorized**

**Problem:** API key rejected

**Solution:**
- Verify API key matches `API_KEYS` in `.env`
- Check for extra spaces or quotes in the key
- Ensure you're using `Authorization: Bearer <key>` header

#### 4. **No Models Found**

**Problem:** Model list is empty

**Solution:**
- Check Ollama is running: `ollama list`
- Pull a model: `ollama pull deepseek-r1`
- Verify `OLLAMA_BASE_URL` in `.env` is correct

---

## 🎨 Customization

### Styling

The demo uses Tailwind CSS via CDN. To customize:

```html
<!-- Change color scheme -->
<script>
  tailwind.config = {
    theme: {
      extend: {
        colors: {
          primary: {
            DEFAULT: '#your-color'
          }
        }
      }
    }
  };
</script>
```

### Features to Add

Consider extending this demo with:

- 🎙️ **Voice Input** (Web Speech API)
- 📝 **Markdown Rendering** (for formatted responses)
- 💾 **Chat History** (localStorage)
- 🎨 **Syntax Highlighting** (for code blocks)
- 📊 **Usage Analytics** (track token usage)
- 🌙 **Dark Mode** (theme switching)

---

## 📚 Learn More

- **OllaBridge Docs:** [GitHub Repository](https://github.com/ruslanmv/ollabridge)
- **Ollama Docs:** [https://ollama.ai](https://ollama.ai)
- **OpenAI API Reference:** [https://platform.openai.com/docs/api-reference](https://platform.openai.com/docs/api-reference)

---

## 🤝 Contributing

Found a bug or have an idea for improvement?

1. Fork the repository
2. Create your feature branch
3. Submit a pull request

We welcome contributions! 🎉

---

## 📄 License

This example is part of the OllaBridge project and is licensed under the MIT License.

---

## ⭐ Support

If this example helped you:

- ⭐ **Star the repository** on GitHub
- 🐛 **Report issues** you encounter
- 💡 **Share your use cases** in Discussions
- 📣 **Spread the word** about OllaBridge

---

<div align="center">

**Made with ❤️ by the OllaBridge Community**

[GitHub](https://github.com/ruslanmv/ollabridge) • [Issues](https://github.com/ruslanmv/ollabridge/issues) • [Discussions](https://github.com/ruslanmv/ollabridge/discussions)

</div>
