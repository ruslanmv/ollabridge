#!/usr/bin/env bash
# Start all required services for OllaBridge demo

set -e

echo "╭────────────────────────────────────────────────────╮"
echo "│                                                    │"
echo "│  🚀 Starting OllaBridge Demo Services             │"
echo "│                                                    │"
echo "╰────────────────────────────────────────────────────╯"
echo ""

# Detect and activate virtual environment if it exists
if [ -d "../.venv" ]; then
    echo "🐍 Activating virtual environment..."
    source ../.venv/bin/activate
    echo "   ✅ Using venv: $(which python3)"
    echo ""
elif [ -d "../../.venv" ]; then
    echo "🐍 Activating virtual environment..."
    source ../../.venv/bin/activate
    echo "   ✅ Using venv: $(which python3)"
    echo ""
fi

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama is not installed!"
    echo ""
    echo "Please install Ollama first:"
    echo "  • Visit: https://ollama.ai"
    echo "  • Or run: curl https://ollama.ai/install.sh | sh"
    echo ""
    exit 1
fi

# Check if OllaBridge is installed (use current Python environment)
if ! python3 -c "import ollabridge" 2>/dev/null; then
    echo "❌ OllaBridge is not installed in current environment!"
    echo ""
    if [ -d "../.venv" ] || [ -d "../../.venv" ]; then
        echo "Installing OllaBridge in virtual environment..."
        cd ..
        pip install -e .
        cd example
    else
        echo "Installing OllaBridge..."
        pip install ollabridge
    fi
    echo ""
    # Verify installation
    if ! python3 -c "import ollabridge" 2>/dev/null; then
        echo "❌ Failed to install OllaBridge"
        echo "Please install manually: cd .. && pip install -e ."
        exit 1
    fi
    echo "✅ OllaBridge installed successfully"
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1️⃣  Starting Ollama..."
echo ""

# Check if Ollama is already running
if pgrep -x "ollama" > /dev/null; then
    echo "   ✅ Ollama is already running"
else
    echo "   Starting Ollama in background..."
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    sleep 2

    if pgrep -x "ollama" > /dev/null; then
        echo "   ✅ Ollama started successfully"
    else
        echo "   ❌ Failed to start Ollama"
        echo "   Check logs: cat /tmp/ollama.log"
        exit 1
    fi
fi

echo ""
echo "2️⃣  Checking for models..."
echo ""

# Wait for Ollama to be ready
for i in {1..10}; do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Check if any models are available and get the first one
MODEL_NAME=""
if curl -s http://localhost:11434/api/tags | grep -q '"models":\['; then
    echo "   ✅ Models available:"
    curl -s http://localhost:11434/api/tags | grep '"name"' | head -3 | sed 's/.*"name":"\([^"]*\)".*/      - \1/'
    # Get the first available model
    MODEL_NAME=$(curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
else
    echo "   ⚠️  No models found!"
    echo "   Pulling llama3 (this may take a few minutes)..."
    ollama pull llama3
    MODEL_NAME="llama3"
fi

if [ -z "$MODEL_NAME" ]; then
    MODEL_NAME="llama3"
fi
echo "   ✅ Demo will use model: $MODEL_NAME"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "3️⃣  Configuring OllaBridge..."
echo ""

# Create .env if it doesn't exist
if [ ! -f ../.env ]; then
    echo "   Creating .env file..."
    cat > ../.env << 'ENVEOF'
# Server Configuration
HOST=0.0.0.0
PORT=11435

# Authentication
API_KEYS=dev-key-change-me

# CORS - IMPORTANT for browser demo!
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000

# Ollama Backend
OLLAMA_BASE_URL=http://localhost:11434

# Default Model
DEFAULT_MODEL=llama3
ENVEOF
    echo "   ✅ .env created"
else
    echo "   ✅ .env exists"

    # Check CORS
    if ! grep -q "CORS_ORIGINS.*localhost:3000" ../.env; then
        echo "   ⚠️  Updating CORS configuration..."
        if grep -q "^CORS_ORIGINS=" ../.env; then
            sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000|' ../.env
        else
            echo "CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000" >> ../.env
        fi
    fi
fi

echo ""
echo "4️⃣  Starting OllaBridge..."
echo ""

# Stop any existing OllaBridge instance
pkill -f "ollabridge" 2>/dev/null || true
sleep 1

# Start OllaBridge in background (use python module to ensure correct environment)
cd ..

# Try to use ollabridge command with the detected model, fallback to python module
if command -v ollabridge &> /dev/null; then
    echo "   Using ollabridge command from: $(which ollabridge)"
    nohup ollabridge start --model "$MODEL_NAME" > /tmp/ollabridge.log 2>&1 &
else
    echo "   Using python module directly"
    nohup python3 -m ollabridge.cli.main start --model "$MODEL_NAME" > /tmp/ollabridge.log 2>&1 &
fi

# Wait for OllaBridge to become healthy (model pulls can take time)
echo "   Waiting for OllaBridge to start (this may take up to 60s if pulling models)..."
for i in {1..60}; do
    if curl -s http://localhost:11435/health > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Check if OllaBridge started
if curl -s http://localhost:11435/health > /dev/null 2>&1; then
    echo "   ✅ OllaBridge started successfully"
    curl -s http://localhost:11435/health | python3 -m json.tool 2>/dev/null | grep -E "(status|node_count)" | sed 's/^/      /' || true
else
    echo "   ❌ Failed to start OllaBridge after 60 seconds"
    echo "   Check logs: cat /tmp/ollabridge.log"
    echo ""
    echo "   Last 20 lines of log:"
    tail -20 /tmp/ollabridge.log | sed 's/^/      /'
    echo ""
    exit 1
fi

cd example

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ All services started!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 Service Status:"
echo "   • Ollama:     ✅ Running (port 11434)"
echo "   • OllaBridge: ✅ Running (port 11435)"
echo ""
echo "📋 Logs:"
echo "   • Ollama:     tail -f /tmp/ollama.log"
echo "   • OllaBridge: tail -f /tmp/ollabridge.log"
echo ""
echo "🚀 Next Steps:"
echo "   1. Run: make run"
echo "   2. Open: http://localhost:3000"
echo "   3. Click: Connect"
echo "   4. Test: What is the capital of Italy?"
echo ""
echo "🛑 To stop services:"
echo "   pkill -f ollama"
echo "   pkill -f ollabridge"
echo ""
