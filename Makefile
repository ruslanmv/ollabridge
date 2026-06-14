# OllaBridge Makefile
# Professional build automation with uv support
#
# Quick start:
#   make install    - Install OllaBridge: backend + frontend (ultra-fast with uv)
#   make run        - Start backend + frontend (full stack)
#   make start-cli  - Start backend only (CLI mode)
#   make dev        - Start in development mode (auto-reload)
#   make mcp        - Start MCP server

.DEFAULT_GOAL := help

# ================================
# Variables
# ================================

# ── OS portability ─────────────────────────────────────────────────────
# The recipes in this Makefile are written for a POSIX shell. On Windows,
# GNU Make defaults to cmd.exe, which cannot run them ("-f was unexpected
# at this time"). We handle Windows in two tiers:
#   1. If a POSIX sh is on PATH (Git for Windows ships sh.exe), use it —
#      every target works unchanged.
#   2. Otherwise fall back to cmd-compatible recipes for the install
#      targets and point users at Git Bash/WSL for the rest.
ifeq ($(OS),Windows_NT)
  VENV_PYTHON := .venv/Scripts/python.exe
  SYS_PYTHON := python
  SH_ON_PATH := $(strip $(shell where sh 2>nul))
  ifneq ($(SH_ON_PATH),)
    SHELL := sh
    HAVE_SH := 1
  else
    HAVE_SH :=
  endif
else
  VENV_PYTHON := .venv/bin/python3
  SYS_PYTHON := python3
  HAVE_SH := 1
endif

# Use venv Python if available, otherwise system Python. Pure-make check
# ($(wildcard) instead of a $(shell if [ -f ... ]) test) so parsing the
# Makefile never invokes a shell — this is what broke `make install` under
# cmd.exe before any recipe even ran.
PYTHON := $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),$(SYS_PYTHON))
UV := uv
PIP := pip
PYTEST := pytest
BLACK := black
RUFF := ruff
MYPY := mypy

SRC_DIR := src/ollabridge
TESTS_DIR := tests
DIST_DIR := dist
BUILD_DIR := build

# Colors for pretty output (disabled under plain cmd.exe, which would
# print the raw escape sequences)
ifeq ($(HAVE_SH),)
COLOR_RESET :=
COLOR_BOLD :=
COLOR_GREEN :=
COLOR_BLUE :=
COLOR_YELLOW :=
COLOR_CYAN :=
else
COLOR_RESET := \033[0m
COLOR_BOLD := \033[1m
COLOR_GREEN := \033[32m
COLOR_BLUE := \033[34m
COLOR_YELLOW := \033[33m
COLOR_CYAN := \033[36m
endif

# ================================
# Help Target (Default)
# ================================

ifeq ($(HAVE_SH),)
.PHONY: help
help: ## Show this help message
	@echo.
	@echo  ==================================================================
	@echo    OllaBridge - your PC as a private, OpenAI-compatible AI server
	@echo  ==================================================================
	@echo.
	@echo  FIRST TIME HERE? Just run these two commands:
	@echo.
	@echo     make install          installs backend + frontend into .venv
	@echo                           (safe - never touches your system Python)
	@echo     make run              starts backend + dashboard at
	@echo                           http://localhost:11435/ui
	@echo.
	@echo  EVERYDAY COMMANDS
	@echo.
	@echo     make run              start backend + frontend dashboard
	@echo     make start            start backend only (sets up Ollama + model)
	@echo     make dev              start with auto-reload (for development)
	@echo     make doctor           check that everything is working
	@echo     make test             run the test suite
	@echo     make install-dev      install incl. dev tools (pytest, ruff)
	@echo.
	@echo  FRONTEND (web dashboard)
	@echo.
	@echo     make ui-install       install frontend dependencies
	@echo     make ui-dev           development (hot reload, proxied to the API)
	@echo     make ui-build         production build (served at /ui when the
	@echo                           gateway is running)
	@echo.
	@echo  AFTER INSTALLING, you can also use the CLI directly:
	@echo.
	@echo     .venv\Scripts\activate         activate the environment once
	@echo     ollabridge start               start the local gateway
	@echo     ollabridge login               pair with OllaBridge Cloud (optional)
	@echo     ollabridge doctor              full diagnostics
	@echo     ollabridge providers add ...   add OpenAI/Anthropic/... keys (BYOK)
	@echo.
	@echo  NEED MORE? Advanced targets (ui-*, build, publish, format, lint)
	@echo  use a POSIX shell. You already have one if Git is installed:
	@echo  open "Git Bash" from the Start menu and run the same make commands.
	@echo.
	@echo  Docs: README.md ^| docs/QUICKSTART.md ^| https://github.com/ruslanmv/ollabridge
	@echo.
else
.PHONY: help
help: ## Show this help message
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)OllaBridge$(COLOR_RESET) — your PC as a private, OpenAI-compatible AI server"
	@echo ""
	@echo "$(COLOR_BOLD)New here? Two commands:$(COLOR_RESET)"
	@echo "  $(COLOR_GREEN)make install$(COLOR_RESET)   # installs backend + frontend into .venv (never touches system Python)"
	@echo "  $(COLOR_GREEN)make run$(COLOR_RESET)       # starts backend + dashboard at http://localhost:11435/ui"
	@echo ""
	@echo "$(COLOR_BOLD)Usage:$(COLOR_RESET)"
	@echo "  make $(COLOR_GREEN)<target>$(COLOR_RESET)"
	@echo ""
	@echo "$(COLOR_BOLD)Installation:$(COLOR_RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; /^install/ {printf "  $(COLOR_GREEN)%-20s$(COLOR_RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(COLOR_BOLD)Running:$(COLOR_RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; /^(run|start|dev)/ {printf "  $(COLOR_GREEN)%-20s$(COLOR_RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(COLOR_BOLD)Development:$(COLOR_RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; /^(mcp|logs|env)/ {printf "  $(COLOR_GREEN)%-20s$(COLOR_RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(COLOR_BOLD)Testing & Quality:$(COLOR_RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; /^(test|format|lint|type|check)/ {printf "  $(COLOR_GREEN)%-20s$(COLOR_RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(COLOR_BOLD)Frontend (UI):$(COLOR_RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; /^ui-/ {printf "  $(COLOR_GREEN)%-20s$(COLOR_RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(COLOR_BOLD)Build & Publish:$(COLOR_RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; /^(build|publish|clean)/ {printf "  $(COLOR_GREEN)%-20s$(COLOR_RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(COLOR_BOLD)Frontend workflow:$(COLOR_RESET)"
	@echo "  $(COLOR_CYAN)make ui-install$(COLOR_RESET)   # Install frontend dependencies"
	@echo "  $(COLOR_CYAN)make ui-dev$(COLOR_RESET)       # Development (hot-reload, proxied to OllaBridge API)"
	@echo "  $(COLOR_CYAN)make ui-build$(COLOR_RESET)     # Production build (served at /ui when gateway is running)"
	@echo ""
	@echo "$(COLOR_BOLD)Examples:$(COLOR_RESET)"
	@echo "  $(COLOR_CYAN)make install$(COLOR_RESET)      # Install OllaBridge: backend + frontend (ultra-fast with uv)"
	@echo "  $(COLOR_CYAN)make run$(COLOR_RESET)          # Start full stack (backend + UI dashboard)"
	@echo "  $(COLOR_CYAN)make start-cli$(COLOR_RESET)    # Start backend only (CLI mode)"
	@echo "  $(COLOR_CYAN)make dev-full$(COLOR_RESET)     # Development: backend + frontend hot reload"
	@echo "  $(COLOR_CYAN)make test$(COLOR_RESET)         # Run all tests"
	@echo ""
endif  # HAVE_SH (help)

# ================================
# Installation Targets
# ================================

# Installs always target a virtual environment — never the system Python.
# Without this, `pip install -e .` on Windows tries to write into
# C:\Python311 and dies with "[WinError 5] Access is denied"; on Linux it
# would need sudo. Precedence: an already-activated virtualenv (VIRTUAL_ENV)
# is respected; otherwise ./.venv is created on demand and used.

ifeq ($(HAVE_SH),)
# ── Windows cmd.exe fallback (no POSIX sh on PATH) ─────────────────────
# Minimal, cmd-native recipes. For the full experience (colors, dev
# targets, frontend builds), run make from Git Bash or WSL.

# cmd.exe needs backslashes when a path is used as the command itself.
VENV_PY_CMD := .venv\Scripts\python.exe

.PHONY: install
install: ## Install OllaBridge (ultra-fast with uv)
	@echo Installing OllaBridge...
	@if not defined VIRTUAL_ENV if not exist $(VENV_PY_CMD) (echo Creating virtual environment .venv... && python -m venv .venv)
	@if defined VIRTUAL_ENV (python -m pip install -e .) else ($(VENV_PY_CMD) -m pip install -e .)
	@if exist frontend\package.json (where pnpm >nul 2>&1 || where npm >nul 2>&1 || echo Frontend skipped: Node.js not found - install it from https://nodejs.org, then run: make ui-install)
	@if exist frontend\package.json (where pnpm >nul 2>&1 && (cd frontend && pnpm install) || (where npm >nul 2>&1 && ((cd frontend && npm install --no-audit --no-fund) || echo Frontend dependency install FAILED - see the npm errors above, then run: make ui-install)))
	@echo Installation complete.
	@if not defined VIRTUAL_ENV echo Activate it with: .venv\Scripts\activate
	@echo Try: make run

.PHONY: install-dev
install-dev: ## Install with development dependencies (testing, linting)
	@echo Installing OllaBridge with dev dependencies...
	@if not defined VIRTUAL_ENV if not exist $(VENV_PY_CMD) (echo Creating virtual environment .venv... && python -m venv .venv)
	@if defined VIRTUAL_ENV (python -m pip install -e ".[dev]") else ($(VENV_PY_CMD) -m pip install -e ".[dev]")
	@echo Installation complete.
	@if not defined VIRTUAL_ENV echo Activate it with: .venv\Scripts\activate

else
# ── POSIX shell recipes (Linux, macOS, Git Bash / WSL on Windows) ──────

.PHONY: install
install: ## Install OllaBridge (ultra-fast with uv)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Installing OllaBridge...$(COLOR_RESET)"
	@if [ -z "$$VIRTUAL_ENV" ] && [ ! -f $(VENV_PYTHON) ]; then \
		echo "$(COLOR_CYAN)Creating virtual environment (.venv)...$(COLOR_RESET)"; \
		{ command -v $(UV) >/dev/null 2>&1 && $(UV) venv .venv; } || $(SYS_PYTHON) -m venv .venv; \
	fi
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "$(COLOR_CYAN)✓ Using uv (ultra-fast installation)$(COLOR_RESET)"; \
		if [ -n "$$VIRTUAL_ENV" ]; then $(UV) pip install -e .; \
		else $(UV) pip install --python $(VENV_PYTHON) -e .; fi; \
	else \
		echo "$(COLOR_YELLOW)⚠ uv not found. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh$(COLOR_RESET)"; \
		echo "$(COLOR_CYAN)Falling back to pip...$(COLOR_RESET)"; \
		if [ -n "$$VIRTUAL_ENV" ]; then python -m pip install -e .; \
		else $(VENV_PYTHON) -m pip install -e .; fi; \
	fi
	@# Fix empty .pth file for editable installs (common issue with uv/pip + src layout)
	@if [ -f .venv/lib/python*/site-packages/_ollabridge.pth ]; then \
		PTH_FILE=$$(find .venv/lib/python*/site-packages/_ollabridge.pth 2>/dev/null | head -1); \
		if [ -n "$$PTH_FILE" ] && [ ! -s "$$PTH_FILE" ]; then \
			echo "$(CYAN)Fixing editable install path...$(COLOR_RESET)"; \
			echo "$$(pwd)/src" > "$$PTH_FILE"; \
		fi \
	fi
	@# Frontend dependencies (best effort — backend works without them)
	@if [ -d frontend ]; then \
		if command -v pnpm >/dev/null 2>&1; then \
			echo "$(COLOR_CYAN)Installing frontend dependencies (pnpm)...$(COLOR_RESET)"; \
			(cd frontend && pnpm install --silent) || \
				echo "$(COLOR_YELLOW)⚠ Frontend install failed — backend still works. Retry with: make ui-install$(COLOR_RESET)"; \
		elif command -v npm >/dev/null 2>&1; then \
			echo "$(COLOR_CYAN)Installing frontend dependencies (npm)...$(COLOR_RESET)"; \
			(cd frontend && npm install --no-audit --no-fund --loglevel=error) || \
				echo "$(COLOR_YELLOW)⚠ Frontend install failed — backend still works. Retry with: make ui-install$(COLOR_RESET)"; \
		else \
			echo "$(COLOR_YELLOW)⚠ Node.js not found — frontend skipped (backend still works).$(COLOR_RESET)"; \
			echo "$(COLOR_YELLOW)  Install Node from https://nodejs.org, then run: make ui-install$(COLOR_RESET)"; \
		fi \
	fi
	@echo "$(COLOR_GREEN)✓ Installation complete!$(COLOR_RESET)"
	@if [ -z "$$VIRTUAL_ENV" ]; then \
		echo "$(COLOR_CYAN)Installed into .venv — activate with: source .venv/bin/activate$(COLOR_RESET)"; \
		echo "$(COLOR_CYAN)(Git Bash on Windows: source .venv/Scripts/activate)$(COLOR_RESET)"; \
	fi
	@echo "$(COLOR_BOLD)Try: make run$(COLOR_RESET)"

.PHONY: install-dev
install-dev: ## Install with development dependencies (testing, linting)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Installing OllaBridge with dev dependencies...$(COLOR_RESET)"
	@if [ -z "$$VIRTUAL_ENV" ] && [ ! -f $(VENV_PYTHON) ]; then \
		echo "$(COLOR_CYAN)Creating virtual environment (.venv)...$(COLOR_RESET)"; \
		{ command -v $(UV) >/dev/null 2>&1 && $(UV) venv .venv; } || $(SYS_PYTHON) -m venv .venv; \
	fi
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "$(COLOR_CYAN)✓ Using uv (ultra-fast installation)$(COLOR_RESET)"; \
		if [ -n "$$VIRTUAL_ENV" ]; then $(UV) pip install -e ".[dev]"; \
		else $(UV) pip install --python $(VENV_PYTHON) -e ".[dev]"; fi; \
	else \
		echo "$(COLOR_YELLOW)⚠ uv not found. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh$(COLOR_RESET)"; \
		echo "$(COLOR_CYAN)Falling back to pip...$(COLOR_RESET)"; \
		if [ -n "$$VIRTUAL_ENV" ]; then python -m pip install -e ".[dev]"; \
		else $(VENV_PYTHON) -m pip install -e ".[dev]"; fi; \
	fi
	@# Fix empty .pth file for editable installs (common issue with uv/pip + src layout)
	@if [ -f .venv/lib/python*/site-packages/_ollabridge.pth ]; then \
		PTH_FILE=$$(find .venv/lib/python*/site-packages/_ollabridge.pth 2>/dev/null | head -1); \
		if [ -n "$$PTH_FILE" ] && [ ! -s "$$PTH_FILE" ]; then \
			echo "$(CYAN)Fixing editable install path...$(COLOR_RESET)"; \
			echo "$$(pwd)/src" > "$$PTH_FILE"; \
		fi \
	fi
	@echo "$(COLOR_GREEN)✓ Development installation complete!$(COLOR_RESET)"

endif  # HAVE_SH (install targets)

ifeq ($(HAVE_SH),)
# ── Windows cmd.exe: everyday targets ──────────────────────────────────
# Single-command recipes that work without a POSIX shell, so beginners on
# plain cmd can install, start, and diagnose without extra tooling.

.PHONY: env
env: ## Create .env file from example if not exists
	@if not exist .env if exist .env.example copy .env.example .env >nul

.PHONY: run
run: env ## Start everything: backend + frontend dashboard (recommended)
	@if not exist $(VENV_PY_CMD) (echo Run "make install" first. && exit /b 1)
	@REM Always rebuild the dashboard so a fresh "git pull" is never served stale.
	@if exist frontend\package.json if exist frontend\dist rmdir /s /q frontend\dist
	@if exist frontend\package.json $(MAKE) ui-build
	@echo Dashboard: http://localhost:11435/ui    API: http://localhost:11435/v1
	@$(VENV_PY_CMD) -m ollabridge.cli.main start --no-setup --auth-mode local-trust --log-level info

.PHONY: start
start: env ## Start OllaBridge (auto-setup Ollama + model)
	@if not exist $(VENV_PY_CMD) (echo Run "make install" first. && exit /b 1)
	@$(VENV_PY_CMD) -m ollabridge.cli.main start

.PHONY: start-cli
start-cli: env ## Start OllaBridge with full CLI setup
	@if not exist $(VENV_PY_CMD) (echo Run "make install" first. && exit /b 1)
	@$(VENV_PY_CMD) -m ollabridge.cli.main start

.PHONY: dev
dev: env ## Start backend in dev mode (auto-reload)
	@if not exist $(VENV_PY_CMD) (echo Run "make install" first. && exit /b 1)
	@$(VENV_PY_CMD) -m ollabridge.cli.main start --host 127.0.0.1 --port 11435 --reload --log-level info

.PHONY: doctor
doctor: ## Diagnose local setup (gateway, Ollama, security)
	@if not exist $(VENV_PY_CMD) (echo Run "make install" first. && exit /b 1)
	@$(VENV_PY_CMD) -m ollabridge.cli.main doctor

.PHONY: test
test: ## Run unit tests
	@if not exist $(VENV_PY_CMD) (echo Run "make install" first. && exit /b 1)
	@$(VENV_PY_CMD) -m pytest tests/ --ignore=tests/integration

.PHONY: ui-install
ui-install: ## Install frontend dependencies
	@where pnpm >nul 2>&1 || where npm >nul 2>&1 || (echo Node.js is required for the frontend. Install it from https://nodejs.org && exit /b 1)
	@where pnpm >nul 2>&1 && (cd frontend && pnpm install) || (cd frontend && npm install --no-audit --no-fund)

.PHONY: ui-dev
ui-dev: ## Start frontend dev server (hot reload, proxied to OllaBridge)
	@where pnpm >nul 2>&1 || where npm >nul 2>&1 || (echo Node.js is required for the frontend. Install it from https://nodejs.org && exit /b 1)
	@echo Frontend dev server: http://localhost:5173 (proxies API to :11435)
	@where pnpm >nul 2>&1 && (cd frontend && pnpm run dev) || (cd frontend && npm run dev)

.PHONY: ui-build
ui-build: ## Build frontend for production (served at /ui)
	@where pnpm >nul 2>&1 || where npm >nul 2>&1 || (echo Node.js is required for the frontend. Install it from https://nodejs.org && exit /b 1)
	@if not exist frontend\node_modules $(MAKE) ui-install
	@where pnpm >nul 2>&1 && (cd frontend && pnpm run build) || (cd frontend && npm run build)
	@echo Frontend built. It is served at /ui when the gateway is running.

# Any other target needs a POSIX shell — explain instead of erroring out
# with cmd syntax noise. (The empty Makefile rule stops make's makefile-
# remake logic from hitting .DEFAULT.)
Makefile: ;

.DEFAULT:
	@echo.
	@echo  The target "$@" needs a POSIX shell and is not available in
	@echo  plain cmd.exe mode. You already have one if Git is installed:
	@echo  open "Git Bash" from the Start menu and run:  make $@
	@echo.

else
# ── POSIX shell targets (everything below) ─────────────────────────────

.PHONY: install-pip
install-pip: ## Install with pip (fallback if uv unavailable)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Installing OllaBridge with pip...$(COLOR_RESET)"
	@if [ -z "$$VIRTUAL_ENV" ] && [ ! -f $(VENV_PYTHON) ]; then \
		echo "$(COLOR_CYAN)Creating virtual environment (.venv)...$(COLOR_RESET)"; \
		$(SYS_PYTHON) -m venv .venv; \
	fi
	@if [ -n "$$VIRTUAL_ENV" ]; then python -m pip install -e .; \
	else $(VENV_PYTHON) -m pip install -e .; fi
	@# Fix empty .pth file for editable installs (common issue with uv/pip + src layout)
	@if [ -f .venv/lib/python*/site-packages/_ollabridge.pth ]; then \
		PTH_FILE=$$(find .venv/lib/python*/site-packages/_ollabridge.pth 2>/dev/null | head -1); \
		if [ -n "$$PTH_FILE" ] && [ ! -s "$$PTH_FILE" ]; then \
			echo "$(CYAN)Fixing editable install path...$(COLOR_RESET)"; \
			echo "$$(pwd)/src" > "$$PTH_FILE"; \
		fi \
	fi
	@echo "$(COLOR_GREEN)✓ Installation complete!$(COLOR_RESET)"

.PHONY: install-uv
install-uv: ## Install uv package manager
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Installing uv...$(COLOR_RESET)"
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "$(COLOR_GREEN)✓ uv already installed$(COLOR_RESET)"; \
		$(UV) --version; \
	else \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
		echo "$(COLOR_GREEN)✓ uv installed successfully$(COLOR_RESET)"; \
	fi

.PHONY: upgrade
upgrade: ## Upgrade all dependencies to latest versions
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Upgrading dependencies...$(COLOR_RESET)"
	@if command -v $(UV) >/dev/null 2>&1; then \
		if [ -n "$$VIRTUAL_ENV" ]; then $(UV) pip install --upgrade -e ".[dev]"; \
		else $(UV) pip install --python $(VENV_PYTHON) --upgrade -e ".[dev]"; fi; \
	else \
		if [ -n "$$VIRTUAL_ENV" ]; then python -m pip install --upgrade -e ".[dev]"; \
		else $(VENV_PYTHON) -m pip install --upgrade -e ".[dev]"; fi; \
	fi
	@echo "$(COLOR_GREEN)✓ Dependencies upgraded!$(COLOR_RESET)"

# ================================
# Start Targets
# ================================

.PHONY: run
run: env ## Start everything: backend + frontend dashboard (always fresh build)
	@echo "$(COLOR_CYAN)Rebuilding the dashboard so it matches the current code...$(COLOR_RESET)"
	@rm -rf frontend/dist
	@$(MAKE) start

.PHONY: start
start: env ui-build ## Start OllaBridge (backend + frontend, configure from UI)
	@echo ""
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(COLOR_RESET)"
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)  OllaBridge — AI Pipeline Builder + Control Tower$(COLOR_RESET)"
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(COLOR_RESET)"
	@echo ""
	@echo "$(COLOR_GREEN)  Dashboard UI:$(COLOR_RESET)  http://localhost:11435/ui"
	@echo "$(COLOR_GREEN)  Backend API:$(COLOR_RESET)   http://localhost:11435/v1"
	@echo "$(COLOR_GREEN)  Health:$(COLOR_RESET)        http://localhost:11435/health"
	@echo ""
	@echo "$(COLOR_CYAN)  Configure models, backends, and auth from the dashboard.$(COLOR_RESET)"
	@echo "$(COLOR_CYAN)  The dashboard opens in your browser automatically once ready.$(COLOR_RESET)"
	@echo "$(COLOR_CYAN)  Press Ctrl+C to stop$(COLOR_RESET)"
	@echo ""
	@# The gateway opens the dashboard itself once /health is ready
	@# (cross-platform, opt out with OLLABRIDGE_NO_BROWSER=1 or --no-open).
	@$(PYTHON) -m ollabridge.cli.main start --no-setup --auth-mode local-trust --log-level info

.PHONY: start-cli
start-cli: env ## Start OllaBridge with full CLI setup (installs Ollama + pulls model)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Starting OllaBridge gateway (full setup)...$(COLOR_RESET)"
	$(PYTHON) -m ollabridge.cli.main start

.PHONY: start-pair
start-pair: env ## Start OllaBridge with pairing code auth (show code on screen)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Starting OllaBridge in pairing mode...$(COLOR_RESET)"
	$(PYTHON) -m ollabridge.cli.main start --auth-mode pairing

.PHONY: start-share
start-share: env ## Start OllaBridge with public URL (ngrok tunnel)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Starting OllaBridge with public sharing...$(COLOR_RESET)"
	$(PYTHON) -m ollabridge.cli.main start --share

# ================================
# Development Targets
# ================================

.PHONY: dev
dev: env ## Start backend in dev mode (auto-reload, no frontend build)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Starting OllaBridge in development mode...$(COLOR_RESET)"
	@echo "$(COLOR_CYAN)Auto-reload enabled. Edit code and see changes instantly.$(COLOR_RESET)"
	$(PYTHON) -m ollabridge.cli.main start --host 0.0.0.0 --port 11435 --reload --log-level info

.PHONY: dev-full
dev-full: env ## Start backend (dev mode) + frontend (hot reload) concurrently
	@echo ""
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(COLOR_RESET)"
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)  OllaBridge — Full-Stack Development Mode$(COLOR_RESET)"
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(COLOR_RESET)"
	@echo ""
	@echo "$(COLOR_GREEN)  Backend API:$(COLOR_RESET)   http://localhost:11435/v1   (auto-reload)"
	@echo "$(COLOR_GREEN)  Frontend UI:$(COLOR_RESET)   http://localhost:3000       (hot reload)"
	@echo "$(COLOR_GREEN)  Health:$(COLOR_RESET)        http://localhost:11435/health"
	@echo ""
	@echo "$(COLOR_CYAN)  Frontend proxies API calls to backend$(COLOR_RESET)"
	@echo "$(COLOR_CYAN)  Press Ctrl+C to stop both$(COLOR_RESET)"
	@echo ""
	@# Run backend and frontend concurrently; kill both on Ctrl+C
	@trap 'kill 0' INT TERM; \
	$(PYTHON) -m ollabridge.cli.main start --host 0.0.0.0 --port 11435 --reload --log-level info & \
	(cd frontend && pnpm dev) & \
	wait

.PHONY: mcp
mcp: ## Start MCP server (Model Context Protocol)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Starting OllaBridge MCP server...$(COLOR_RESET)"
	@echo "$(COLOR_CYAN)MCP server running in stdio mode. Connect with MCP clients.$(COLOR_RESET)"
	$(PYTHON) -m ollabridge.mcp.server

.PHONY: env
env: ## Create .env file from example if not exists
	@if [ ! -f .env ]; then \
		if [ -f .env.example ]; then \
			echo "$(COLOR_CYAN)Creating .env from .env.example...$(COLOR_RESET)"; \
			cp .env.example .env; \
			echo "$(COLOR_GREEN)✓ .env created. Edit it with your configuration.$(COLOR_RESET)"; \
		else \
			echo "$(COLOR_YELLOW)⚠ .env.example not found$(COLOR_RESET)"; \
		fi \
	fi

.PHONY: logs
logs: ## View recent request logs
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)Recent OllaBridge logs:$(COLOR_RESET)"
	@if [ -f ollabridge.db ]; then \
		sqlite3 ollabridge.db "SELECT datetime(timestamp, 'unixepoch'), model, status FROM request_logs ORDER BY timestamp DESC LIMIT 10;"; \
	else \
		echo "$(COLOR_YELLOW)No logs found. Start OllaBridge to generate logs.$(COLOR_RESET)"; \
	fi

# ================================
# Frontend (UI) Targets
# ================================

# Package manager: pnpm preferred (pnpm-lock.yaml), npm as fallback.
# Resolved at recipe time so parsing stays shell-free.
define NODE_PM
$$(command -v pnpm >/dev/null 2>&1 && echo pnpm || echo npm)
endef

.PHONY: ui-install
ui-install: ## Install frontend dependencies
	@command -v pnpm >/dev/null 2>&1 || command -v npm >/dev/null 2>&1 || { \
		echo "$(COLOR_YELLOW)⚠ Node.js is required for the frontend. Install it from https://nodejs.org$(COLOR_RESET)"; exit 1; }
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Installing frontend dependencies ($(NODE_PM))...$(COLOR_RESET)"
	cd frontend && $(NODE_PM) install
	@echo "$(COLOR_GREEN)✓ Frontend dependencies installed!$(COLOR_RESET)"

.PHONY: ui-dev
ui-dev: ## Start frontend dev server (hot reload, proxied to OllaBridge)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Starting frontend dev server...$(COLOR_RESET)"
	@echo "$(COLOR_CYAN)Proxy: localhost:5173 → localhost:11435$(COLOR_RESET)"
	cd frontend && $(NODE_PM) run dev

.PHONY: ui-build
ui-build: ## Build frontend for production (output: frontend/dist/)
	@if [ -d frontend/dist ] && [ -f frontend/dist/index.html ]; then \
		NEWEST_SRC=$$(find frontend/src frontend/index.html frontend/vite.config.ts frontend/tsconfig*.json -newer frontend/dist/index.html 2>/dev/null | head -1); \
		if [ -z "$$NEWEST_SRC" ]; then \
			echo "$(COLOR_GREEN)✓ Frontend already built (no changes detected)$(COLOR_RESET)"; \
			exit 0; \
		fi; \
	fi; \
	if ! command -v pnpm >/dev/null 2>&1 && ! command -v npm >/dev/null 2>&1; then \
		echo "$(COLOR_YELLOW)⚠ Node.js not found — starting without the dashboard UI.$(COLOR_RESET)"; \
		echo "$(COLOR_YELLOW)  Install Node from https://nodejs.org, then: make ui-build$(COLOR_RESET)"; \
		exit 0; \
	fi; \
	if [ ! -d frontend/node_modules ]; then \
		echo "$(COLOR_CYAN)Frontend dependencies missing — installing first...$(COLOR_RESET)"; \
		(cd frontend && $(NODE_PM) install); \
	fi; \
	echo "$(COLOR_BOLD)$(COLOR_GREEN)Building frontend for production...$(COLOR_RESET)"; \
	cd frontend && $(NODE_PM) run build; \
	echo "$(COLOR_GREEN)✓ Frontend built → frontend/dist/$(COLOR_RESET)"; \
	echo "$(COLOR_CYAN)Served at /ui when OllaBridge is running$(COLOR_RESET)"

.PHONY: ui-rebuild
ui-rebuild: ## Force rebuild frontend (ignore cache)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Rebuilding frontend for production...$(COLOR_RESET)"
	cd frontend && $(NODE_PM) run build
	@echo "$(COLOR_GREEN)✓ Frontend rebuilt → frontend/dist/$(COLOR_RESET)"

# ================================
# Testing Targets
# ================================

.PHONY: test
test: ## Run unit tests only (fast, no Ollama required)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Running unit tests...$(COLOR_RESET)"
	@code=0; \
	$(PYTEST) $(TESTS_DIR) -v --ignore=$(TESTS_DIR)/integration/ || code=$$?; \
	if [ $$code -eq 0 ]; then exit 0; fi; \
	if [ $$code -eq 5 ]; then \
		echo "$(COLOR_YELLOW)⚠ No unit tests collected (only integration tests exist).$(COLOR_RESET)"; \
		exit 0; \
	fi; \
	exit $$code

.PHONY: test-all
test-all: ## Run all tests (unit + integration, requires Ollama)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Running all tests (unit + integration)...$(COLOR_RESET)"
	$(PYTEST) $(TESTS_DIR) -v

.PHONY: test-integration
test-integration: ## Run integration tests (requires Ollama running)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Running integration tests...$(COLOR_RESET)"
	@echo "$(COLOR_YELLOW)⚠ Requires: Ollama installed and running (ollama serve)$(COLOR_RESET)"
	@echo "$(COLOR_YELLOW)⚠ Requires: Model pulled (e.g., ollama pull tinyllama)$(COLOR_RESET)"
	@if command -v ollama >/dev/null 2>&1; then \
		$(PYTEST) $(TESTS_DIR)/integration/ -v -s; \
	else \
		echo "$(COLOR_YELLOW)Ollama not found. Install: curl -fsSL https://ollama.com/install.sh | sh$(COLOR_RESET)"; \
		exit 1; \
	fi

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Running tests with coverage...$(COLOR_RESET)"
	$(PYTEST) $(TESTS_DIR) --cov=$(SRC_DIR) --cov-report=html --cov-report=term --ignore=$(TESTS_DIR)/integration/
	@echo "$(COLOR_CYAN)Coverage report: htmlcov/index.html$(COLOR_RESET)"

.PHONY: test-watch
test-watch: ## Run tests in watch mode (requires pytest-watch)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Running tests in watch mode...$(COLOR_RESET)"
	@if command -v ptw >/dev/null 2>&1; then \
		ptw $(TESTS_DIR) --ignore=$(TESTS_DIR)/integration/; \
	else \
		echo "$(COLOR_YELLOW)pytest-watch not installed. Install with: pip install pytest-watch$(COLOR_RESET)"; \
	fi

.PHONY: test-fast
test-fast: ## Run tests in parallel (faster, requires pytest-xdist)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Running tests in parallel...$(COLOR_RESET)"
	$(PYTEST) $(TESTS_DIR) -v -n auto --ignore=$(TESTS_DIR)/integration/

# ================================
# Code Quality Targets
# ================================

.PHONY: format
format: ## Format code with black and ruff
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Formatting code...$(COLOR_RESET)"
	$(BLACK) $(SRC_DIR) $(TESTS_DIR)
	$(RUFF) check $(SRC_DIR) $(TESTS_DIR) --fix
	@echo "$(COLOR_GREEN)✓ Code formatted!$(COLOR_RESET)"

.PHONY: lint
lint: ## Check code quality with ruff
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Linting code...$(COLOR_RESET)"
	$(RUFF) check $(SRC_DIR) $(TESTS_DIR)

.PHONY: type
type: ## Run type checking with mypy
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Type checking...$(COLOR_RESET)"
	$(MYPY) $(SRC_DIR)

.PHONY: check
check: format lint type ## Run all quality checks (format, lint, type)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)✓ All quality checks passed!$(COLOR_RESET)"

# ================================
# Build & Publish Targets
# ================================

.PHONY: build
build: clean ## Build distribution packages
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Building OllaBridge...$(COLOR_RESET)"
	$(PYTHON) -m build
	@echo "$(COLOR_GREEN)✓ Build complete: $(DIST_DIR)/$(COLOR_RESET)"
	@ls -lh $(DIST_DIR)

.PHONY: publish
publish: build ## Publish to PyPI (requires twine)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Publishing to PyPI...$(COLOR_RESET)"
	@echo "$(COLOR_YELLOW)⚠ This will upload to production PyPI. Continue? [y/N]$(COLOR_RESET)"
	@read -r REPLY; \
	if [ "$$REPLY" = "y" ] || [ "$$REPLY" = "Y" ]; then \
		twine upload $(DIST_DIR)/*; \
		echo "$(COLOR_GREEN)✓ Published to PyPI!$(COLOR_RESET)"; \
	else \
		echo "$(COLOR_CYAN)Aborted.$(COLOR_RESET)"; \
	fi

.PHONY: publish-test
publish-test: build ## Publish to TestPyPI (for testing)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Publishing to TestPyPI...$(COLOR_RESET)"
	twine upload --repository testpypi $(DIST_DIR)/*
	@echo "$(COLOR_GREEN)✓ Published to TestPyPI!$(COLOR_RESET)"
	@echo "$(COLOR_CYAN)Install with: pip install --index-url https://test.pypi.org/simple/ ollabridge$(COLOR_RESET)"

.PHONY: clean
clean: ## Clean build artifacts and cache files
	@echo "$(COLOR_BOLD)$(COLOR_YELLOW)Cleaning build artifacts...$(COLOR_RESET)"
	rm -rf $(BUILD_DIR) $(DIST_DIR) *.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.coverage" -delete
	@echo "$(COLOR_GREEN)✓ Cleaned!$(COLOR_RESET)"

.PHONY: clean-all
clean-all: clean ## Clean everything including .env and databases
	@echo "$(COLOR_BOLD)$(COLOR_YELLOW)Cleaning everything (including .env and databases)...$(COLOR_RESET)"
	rm -f .env ollabridge.db
	@echo "$(COLOR_GREEN)✓ Deep clean complete!$(COLOR_RESET)"

# ================================
# Docker Targets (Optional)
# ================================

.PHONY: docker-build
docker-build: ## Build Docker image
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Building Docker image...$(COLOR_RESET)"
	docker build -t ollabridge:latest .
	@echo "$(COLOR_GREEN)✓ Docker image built!$(COLOR_RESET)"

.PHONY: docker-run
docker-run: ## Run OllaBridge in Docker
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)Running OllaBridge in Docker...$(COLOR_RESET)"
	docker run -p 11435:11435 --env-file .env ollabridge:latest

# ================================
# Utility Targets
# ================================

.PHONY: version
version: ## Show OllaBridge version
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)OllaBridge Version:$(COLOR_RESET)"
	@$(PYTHON) -c "import tomli; print(tomli.load(open('pyproject.toml', 'rb'))['project']['version'])" 2>/dev/null || \
		grep "version" pyproject.toml | head -1 | cut -d'"' -f2

.PHONY: info
info: ## Show system information
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)System Information:$(COLOR_RESET)"
	@echo "Python: $$($(PYTHON) --version)"
	@echo "pip: $$($(PIP) --version | cut -d' ' -f1-2)"
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "uv: $$($(UV) --version)"; \
	else \
		echo "uv: $(COLOR_YELLOW)not installed$(COLOR_RESET)"; \
	fi
	@echo ""
	@echo "$(COLOR_BOLD)OllaBridge:$(COLOR_RESET)"
	@if command -v ollabridge >/dev/null 2>&1; then \
		echo "Status: $(COLOR_GREEN)installed$(COLOR_RESET)"; \
	else \
		echo "Status: $(COLOR_YELLOW)not installed$(COLOR_RESET)"; \
	fi

.PHONY: docs
docs: ## Open documentation in browser
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)Opening documentation...$(COLOR_RESET)"
	@if command -v open >/dev/null 2>&1; then \
		open https://github.com/ruslanmv/ollabridge#readme; \
	elif command -v xdg-open >/dev/null 2>&1; then \
		xdg-open https://github.com/ruslanmv/ollabridge#readme; \
	else \
		echo "Visit: https://github.com/ruslanmv/ollabridge#readme"; \
	fi

# ================================
# CI/CD Targets
# ================================

.PHONY: ci
ci: install-dev check test ## Run full CI pipeline (install, check, test)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)✓ CI pipeline complete!$(COLOR_RESET)"

.PHONY: pre-commit
pre-commit: format lint ## Run pre-commit checks (format + lint)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)✓ Pre-commit checks passed!$(COLOR_RESET)"

# ================================
# Special Targets
# ================================

.PHONY: all
all: clean install-dev check test build ## Do everything (clean, install, check, test, build)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)✓ All tasks complete!$(COLOR_RESET)"

# Declare all targets as phony (not files)
.PHONY: help install install-dev install-pip install-uv upgrade \
        run start start-cli start-pair start-share \
        dev dev-full mcp env logs \
        ui-install ui-dev ui-build \
        test test-all test-integration test-cov test-watch test-fast \
        format lint type check \
        build publish publish-test clean clean-all \
        docker-build docker-run \
        version info docs \
        ci pre-commit all

endif  # HAVE_SH (POSIX-only targets)
