#!/usr/bin/env bash
# Debug connection issues with OllaBridge demo

echo "🔍 OllaBridge Connection Debugger"
echo "=================================="
echo ""

# Test 1: Check if Ollama is running
echo "1️⃣  Testing Ollama (port 11434)..."
if curl -s --connect-timeout 2 http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "   ✅ Ollama is responding"
else
    echo "   ❌ Ollama is NOT responding"
    echo "   FIX: Run 'ollama serve' in a separate terminal"
    echo ""
    exit 1
fi
echo ""

# Test 2: Check if OllaBridge is running
echo "2️⃣  Testing OllaBridge (port 11435)..."
if curl -s --connect-timeout 2 http://localhost:11435/health > /dev/null 2>&1; then
    echo "   ✅ OllaBridge is responding"
    curl -s http://localhost:11435/health | python3 -m json.tool 2>/dev/null || true
else
    echo "   ❌ OllaBridge is NOT responding"
    echo "   FIX: Run 'ollabridge start' in a separate terminal"
    echo ""
    exit 1
fi
echo ""

# Test 3: Test API key authentication
echo "3️⃣  Testing API authentication..."
API_KEY=$(grep "^API_KEYS=" ../.env 2>/dev/null | cut -d'=' -f2 | cut -d',' -f1 | tr -d ' "' || echo "dev-key-change-me")
echo "   Using API key: ${API_KEY:0:10}..."

if curl -s --connect-timeout 2 \
    -H "Authorization: Bearer $API_KEY" \
    http://localhost:11435/v1/models > /dev/null 2>&1; then
    echo "   ✅ Authentication working"
else
    echo "   ❌ Authentication failed"
    echo "   FIX: Check API_KEYS in .env file"
    echo ""
    exit 1
fi
echo ""

# Test 4: Check CORS configuration
echo "4️⃣  Checking CORS configuration..."
if grep -q "CORS_ORIGINS.*localhost:3000" ../.env 2>/dev/null; then
    echo "   ✅ CORS includes localhost:3000"
else
    echo "   ⚠️  CORS may not be configured correctly"
    echo "   Current .env CORS setting:"
    grep "CORS_ORIGINS" ../.env 2>/dev/null || echo "   (not found)"
    echo ""
    echo "   FIX: Add to .env file:"
    echo "   CORS_ORIGINS=http://localhost:3000,http://localhost:5173"
    echo ""
fi
echo ""

# Test 5: Test actual chat completion
echo "5️⃣  Testing chat completion endpoint..."
RESPONSE=$(curl -s --connect-timeout 5 \
    -X POST http://localhost:11435/v1/chat/completions \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "llama3",
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 10
    }' 2>&1)

if echo "$RESPONSE" | grep -q "choices"; then
    echo "   ✅ Chat completion working!"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null | head -20 || echo "$RESPONSE"
else
    echo "   ❌ Chat completion failed"
    echo "   Response: $RESPONSE"
    echo ""
    echo "   Possible causes:"
    echo "   - No models available (run: ollama pull llama3)"
    echo "   - Model name mismatch (check available models)"
fi
echo ""

echo "=================================="
echo "✅ Diagnostics complete!"
echo ""
echo "If all tests passed, try the demo again:"
echo "  1. make run"
echo "  2. Open http://localhost:3000"
echo "  3. Click Connect"
echo ""
