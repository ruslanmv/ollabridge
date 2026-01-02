.PHONY: help install run test clean check-ollama check-ollabridge

# Default target
help:
	@echo "================================================"
	@echo "  OllaBridge Demo Client - Make Commands"
	@echo "================================================"
	@echo ""
	@echo "Available commands:"
	@echo ""
	@echo "  make install          - Install OllaBridge (if not already installed)"
	@echo "  make run              - Start the demo web client on port 3000"
	@echo "  make test             - Run health checks and test the client"
	@echo "  make check-ollama     - Verify Ollama is running"
	@echo "  make check-ollabridge - Verify OllaBridge is running"
	@echo "  make clean            - Stop any running servers"
	@echo ""
	@echo "Quick start:"
	@echo "  1. make install"
	@echo "  2. make run"
	@echo "  3. Open http://localhost:3000 in your browser"
	@echo ""

# Install OllaBridge
install:
	@echo "📦 Installing OllaBridge..."
	@if command -v ollabridge > /dev/null 2>&1; then \
		echo "✓ OllaBridge is already installed"; \
		ollabridge --version; \
	else \
		echo "Installing OllaBridge via pip..."; \
		python3 -m pip install --upgrade pip; \
		python3 -m pip install ollabridge; \
		echo "✓ OllaBridge installed successfully"; \
	fi
	@echo ""
	@echo "Next steps:"
	@echo "  1. Ensure Ollama is running (ollama serve)"
	@echo "  2. Pull a model (ollama pull deepseek-r1)"
	@echo "  3. Start OllaBridge (ollabridge start)"
	@echo "  4. Run: make run"
	@echo ""

# Run the demo client web server
run:
	@echo "🌐 Starting demo client web server..."
	@echo ""
	@echo "Server will run on: http://localhost:3000"
	@echo "Press Ctrl+C to stop"
	@echo ""
	@echo "================================================"
	@python3 -m http.server 3000

# Run comprehensive tests
test: check-ollama check-ollabridge
	@echo ""
	@echo "================================================"
	@echo "  Running Demo Client Tests"
	@echo "================================================"
	@echo ""
	@echo "Testing OllaBridge endpoints..."
	@echo ""
	@echo "1. Health Check:"
	@curl -s http://localhost:11435/health | python3 -m json.tool || echo "❌ Health check failed"
	@echo ""
	@echo "2. Models List (requires API key):"
	@curl -s -H "Authorization: Bearer dev-key-change-me" http://localhost:11435/v1/models | python3 -m json.tool || echo "❌ Models check failed"
	@echo ""
	@echo "✅ All tests completed!"
	@echo ""
	@echo "You can now run 'make run' to start the demo client"
	@echo ""

# Check if Ollama is running
check-ollama:
	@echo "Checking Ollama..."
	@if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then \
		echo "✓ Ollama is running"; \
	else \
		echo "❌ Ollama is not running"; \
		echo "   Start it with: ollama serve"; \
		exit 1; \
	fi

# Check if OllaBridge is running
check-ollabridge:
	@echo "Checking OllaBridge..."
	@if curl -s http://localhost:11435/health > /dev/null 2>&1; then \
		echo "✓ OllaBridge is running"; \
	else \
		echo "❌ OllaBridge is not running"; \
		echo "   Start it with: ollabridge start"; \
		exit 1; \
	fi

# Clean up
clean:
	@echo "🧹 Cleaning up..."
	@pkill -f "http.server 3000" 2>/dev/null || echo "No web server to stop"
	@echo "✓ Cleanup complete"
	@echo ""
