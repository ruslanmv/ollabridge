# 🔧 Troubleshooting Guide

## The "Failed to fetch" Error

If you see this error in the browser:
```
> ❌ Connection failed: Failed to fetch
```

### Root Cause

The browser cannot connect to OllaBridge. This happens when:
1. **Ollama is not running** ← Most common cause!
2. **OllaBridge is not running**
3. **CORS is not configured correctly**
4. **Wrong URL or port**

---

## 🚀 Quick Fix (Recommended)

Run these commands in order:

```bash
cd example

# 1. Start all services automatically
make start

# 2. Run the demo
make run

# 3. Open http://localhost:3000 in your browser
```

That's it! The `make start` command will:
- ✅ Start Ollama
- ✅ Pull a model if needed
- ✅ Configure .env with correct CORS
- ✅ Start OllaBridge
- ✅ Verify everything is working

---

## 🔍 Debug Step-by-Step

If `make start` doesn't work, debug manually:

### Step 1: Run the Debugger

```bash
make debug
```

This will test each component and tell you exactly what's wrong.

### Step 2: Fix Each Issue

Based on the debug output, fix the issues:

#### Issue: Ollama not running

**Fix:**
```bash
# Start Ollama in background
ollama serve &

# Or in a separate terminal
ollama serve
```

**Verify:**
```bash
curl http://localhost:11434/api/tags
```

#### Issue: No models available

**Fix:**
```bash
# Pull a model (first time only)
ollama pull llama3

# Verify
ollama list
```

#### Issue: OllaBridge not running

**Fix:**
```bash
# Start OllaBridge in background
cd /path/to/ollabridge
ollabridge start &

# Or in a separate terminal
ollabridge start
```

**Verify:**
```bash
curl http://localhost:11435/health
```

#### Issue: CORS not configured

**Fix:**
```bash
# Edit .env file in project root
nano .env

# Add or update this line:
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000

# Restart OllaBridge
pkill -f ollabridge
ollabridge start &
```

**Verify:**
```bash
grep CORS_ORIGINS .env
```

---

## 📋 Complete Checklist

Use this checklist to verify everything:

```bash
# In example/ directory
make check-setup
```

You should see all ✅:

```
✅ Ollama is installed
✅ Ollama is running on port 11434
✅ Models found
✅ OllaBridge is installed
✅ OllaBridge is running on port 11435
✅ .env file exists
✅ CORS includes localhost:3000
✅ API key configured
```

---

## 🎯 Test the Connection

Once all checks pass, test the actual connection:

```bash
# Run this from example/ directory
make debug
```

You should see:
```
✅ Ollama is responding
✅ OllaBridge is responding
✅ Authentication working
✅ CORS includes localhost:3000
✅ Chat completion working!
```

---

## 🌐 Test in Browser

1. **Start the demo:**
   ```bash
   make run
   ```

2. **Open browser:**
   ```
   http://localhost:3000
   ```

3. **Click "Connect"**
   - Values should be auto-filled
   - Connection should succeed

4. **Send a test prompt:**
   ```
   What is the capital of Italy?
   ```

5. **Expected response:**
   ```
   Rome (or Roma)
   ```

---

## 🐛 Common Issues

### Issue: "Cannot access from file:///"

**Problem:** Opening index.html directly in browser

**Fix:** Must serve via HTTP:
```bash
make run  # Serves on http://localhost:3000
```

### Issue: "CORS policy: No 'Access-Control-Allow-Origin'"

**Problem:** CORS not configured

**Fix:**
```bash
# Edit .env
CORS_ORIGINS=http://localhost:3000

# Restart OllaBridge
pkill -f ollabridge && ollabridge start &
```

### Issue: "Connection refused"

**Problem:** OllaBridge not running

**Fix:**
```bash
# Check if running
curl http://localhost:11435/health

# If not, start it
ollabridge start &
```

### Issue: "Model not found"

**Problem:** Requested model doesn't exist

**Fix:**
```bash
# List available models
ollama list

# Pull a model
ollama pull llama3

# Update DEFAULT_MODEL in .env if needed
```

---

## 🛟 Still Having Issues?

1. **Check logs:**
   ```bash
   tail -f /tmp/ollama.log
   tail -f /tmp/ollabridge.log
   ```

2. **Restart everything:**
   ```bash
   # Stop all services
   pkill -f ollama
   pkill -f ollabridge

   # Start fresh
   make start
   ```

3. **Verify ports:**
   ```bash
   # Check what's using the ports
   lsof -i :11434  # Ollama
   lsof -i :11435  # OllaBridge
   lsof -i :3000   # Demo client
   ```

4. **Check network:**
   ```bash
   # Can you reach localhost?
   ping localhost

   # Are ports accessible?
   telnet localhost 11434
   telnet localhost 11435
   ```

---

## 📞 Get Help

If you've tried everything above and it still doesn't work:

1. **Run full diagnostics:**
   ```bash
   make check-setup > diagnostics.txt
   make debug >> diagnostics.txt
   ```

2. **Share the output** in a GitHub issue

3. **Include:**
   - Operating system (WSL, Mac, Linux)
   - Python version (`python3 --version`)
   - Ollama version (`ollama --version`)
   - Contents of diagnostics.txt

---

## ✅ Success!

When everything works, you should be able to:

1. Run `make start` (starts all services)
2. Run `make run` (opens demo)
3. Click "Connect" in browser
4. Type: "What is the capital of Italy?"
5. Get response: "Rome" or "Roma"

**That's a fully working OllaBridge setup!** 🎉
