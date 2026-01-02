#!/usr/bin/env bash
# OllaBridge Demo Setup Checker
# Run this to verify your environment is properly configured

echo "╭────────────────────────────────────────────────────╮"
echo "│                                                    │"
echo "│  🔍 OllaBridge Setup Checker                      │"
echo "│                                                    │"
echo "╰────────────────────────────────────────────────────╯"
echo ""

ERRORS=0

# Check 1: Ollama installed
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Checking if Ollama is installed..."
if command -v ollama &> /dev/null; then
    echo "   ✅ Ollama is installed"
else
    echo "   ❌ Ollama is NOT installed"
    echo "   → Download from: https://ollama.ai"
    ((ERRORS++))
fi
echo ""

# Check 2: Ollama running
echo "2️⃣  Checking if Ollama is running..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "   ✅ Ollama is running on port 11434"
else
    echo "   ❌ Ollama is NOT running"
    echo "   → Run: ollama serve"
    ((ERRORS++))
fi
echo ""

# Check 3: Models available
echo "3️⃣  Checking if any models are available..."
if curl -s http://localhost:11434/api/tags 2>/dev/null | grep -q "models"; then
    echo "   ✅ Models found:"
    curl -s http://localhost:11434/api/tags 2>/dev/null | grep '"name"' | head -3 | sed 's/.*"name":"\([^"]*\)".*/      - \1/'
else
    echo "   ❌ No models found"
    echo "   → Run: ollama pull llama3"
    ((ERRORS++))
fi
echo ""

# Check 4: OllaBridge installed
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  Checking if OllaBridge is installed..."
if python3 -c "import ollabridge" 2>/dev/null; then
    echo "   ✅ OllaBridge is installed"
else
    echo "   ❌ OllaBridge is NOT installed"
    echo "   → Run: pip install ollabridge"
    ((ERRORS++))
fi
echo ""

# Check 5: OllaBridge running
echo "5️⃣  Checking if OllaBridge is running..."
if curl -s http://localhost:11435/health > /dev/null 2>&1; then
    echo "   ✅ OllaBridge is running on port 11435"
    curl -s http://localhost:11435/health | python3 -m json.tool 2>/dev/null | grep -E "(status|node_count)" | sed 's/^/      /'
else
    echo "   ❌ OllaBridge is NOT running"
    echo "   → Run: ollabridge start"
    ((ERRORS++))
fi
echo ""

# Check 6: .env configuration
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6️⃣  Checking .env configuration..."
if [ -f ../.env ]; then
    echo "   ✅ .env file exists"

    # Check CORS
    if grep -q "CORS_ORIGINS.*localhost:3000" ../.env; then
        echo "   ✅ CORS includes localhost:3000"
    else
        echo "   ⚠️  CORS might not include localhost:3000"
        echo "   → Add to .env: CORS_ORIGINS=http://localhost:3000"
        ((ERRORS++))
    fi

    # Check API key
    if grep -q "^API_KEYS=" ../.env; then
        API_KEY=$(grep "^API_KEYS=" ../.env | cut -d'=' -f2 | cut -d',' -f1 | tr -d ' "')
        echo "   ✅ API key configured: ${API_KEY:0:15}..."
    else
        echo "   ⚠️  API_KEYS not found in .env"
        ((ERRORS++))
    fi
else
    echo "   ❌ .env file NOT found in parent directory"
    echo "   → Create .env file with required settings"
    ((ERRORS++))
fi
echo ""

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
if [ $ERRORS -eq 0 ]; then
    echo "✅ All checks passed! You're ready to go!"
    echo ""
    echo "Next steps:"
    echo "  1. Run: make run"
    echo "  2. Open: http://localhost:3000"
    echo "  3. Click: Connect button"
    echo ""
else
    echo "❌ Found $ERRORS issue(s) - please fix them first"
    echo ""
    echo "Quick fix commands:"
    echo "  • Install Ollama: Download from https://ollama.ai"
    echo "  • Start Ollama: ollama serve"
    echo "  • Pull a model: ollama pull llama3"
    echo "  • Install OllaBridge: pip install ollabridge"
    echo "  • Start OllaBridge: ollabridge start"
    echo "  • Configure CORS: Add CORS_ORIGINS=http://localhost:3000 to .env"
    echo ""
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
