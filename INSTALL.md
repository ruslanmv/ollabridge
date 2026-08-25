# OllaBridge Installation Guide

Multiple installation methods to fit your workflow.

---

## 🚀 Quick Install (Recommended - Ultra Fast with `uv`)

**Fastest method** using our Makefile + `uv`:

```bash
# Clone the repo
git clone https://github.com/ruslanmv/ollabridge.git
cd ollabridge

# Install uv (if not already installed)
make install-uv

# Install OllaBridge (ultra-fast with uv)
make install

# Start the gateway
make start
```

**Why `uv`?**
- ⚡ **10-100x faster** than pip
- 🦀 Written in Rust (blazing fast)
- 🔒 Deterministic installs
- 📦 Drop-in replacement for pip

---

## 📦 Installation Methods

### Method 1: Makefile (Recommended)

**Production installation:**
```bash
make install
```

**Development installation (includes testing, linting tools):**
```bash
make install-dev
```

**See all available commands:**
```bash
make help
```

### Method 2: PyPI (Stable Release)

```bash
pip install ollabridge
```

Or with `uv` (faster):
```bash
uv pip install ollabridge
```

### Method 3: From Source (Development)

```bash
# Clone the repository
git clone https://github.com/ruslanmv/ollabridge.git
cd ollabridge

# Install in editable mode
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

### Method 4: Docker (Containerized)

```bash
# Build the image
make docker-build

# Run OllaBridge
make docker-run
```

---

## 🛠️ Development Setup

For contributors and developers:

```bash
# Install with dev dependencies
make install-dev

# Run tests
make test

# Format code
make format

# Run linter
make lint

# Run all quality checks
make check

# Start in development mode (auto-reload)
make dev
```

---

## ⚡ Installing `uv` (Recommended)

`uv` is an ultra-fast Python package installer written in Rust.

### Linux / macOS

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or use our Makefile:
```bash
make install-uv
```

### Windows

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Verify installation

```bash
uv --version
```

---

## Troubleshooting broken `pip install ollabridge` environments

The OllaBridge wheel exposes these console commands:

```toml
ollabridge = "ollabridge.cli.main:app"
ollabridge-node = "ollabridge.node.cli:app"
ollabridge-mcp = "ollabridge.mcp.server:main"
```

If a console command exists but Python cannot import `ollabridge`, or if `pip`
fails while uninstalling a dependency executable, the Python environment is
inconsistent. Reinstall in a fresh virtual environment first; it avoids mixing
system and per-user packages.

### Windows: missing `websockets.exe` during install

A failure like this means the global `websockets` metadata still records a
script that has already disappeared:

```text
[WinError 2] The system cannot find the file specified:
'C:\Python311\Scripts\websockets.exe' -> 'C:\Python311\Scripts\websockets.exe.deleteme'
```

Use a project virtual environment instead of repairing `C:\Python311`:

```bat
cd C:\workspace\ollabridge
py -3.11 -m venv .venv-win
.venv-win\Scripts\activate
python -m pip install --upgrade pip
python -m pip install --no-cache-dir ollabridge
python -c "import ollabridge; print(ollabridge.__file__)"
ollabridge --help
```

For source development from this checkout, install the repository itself:

```bat
python -m pip install --no-cache-dir -e .
```

Only repair the global installation if you really need it. Close Python/IDE
processes, open PowerShell as Administrator, then remove the broken package and
script metadata before reinstalling:

```powershell
py -3.11 -m pip uninstall -y websockets
Remove-Item -Recurse -Force C:\Python311\Lib\site-packages\websockets -ErrorAction SilentlyContinue
Get-ChildItem C:\Python311\Lib\site-packages -Directory -Filter "websockets-*.dist-info" | Remove-Item -Recurse -Force
Remove-Item C:\Python311\Scripts\websockets.exe* -Force -ErrorAction SilentlyContinue
py -3.11 -m pip install --no-cache-dir --force-reinstall ollabridge
py -3.11 -m pip check
```

### WSL/Linux: command exists but package import fails

A traceback like this means `~/.local/bin/ollabridge` was left behind or was
installed by a different Python interpreter than the one now on `PATH`:

```text
ModuleNotFoundError: No module named 'ollabridge'
```

Keep Linux environments separate from Windows environments and create the venv
on the Linux filesystem:

```bash
mkdir -p ~/.venvs
python3.11 -m venv ~/.venvs/ollabridge
source ~/.venvs/ollabridge/bin/activate
python -m pip install --upgrade pip
python -m pip install --no-cache-dir ollabridge
python -c "import sys, ollabridge; print(sys.executable); print(ollabridge.__file__)"
ollabridge --help
```

When testing this repository from WSL:

```bash
source ~/.venvs/ollabridge/bin/activate
cd /mnt/c/workspace/ollabridge
python -m pip install --no-cache-dir -e .
```

Do not reuse a Windows `.venv` from WSL; console scripts and compiled wheels are
platform-specific.

To clean a broken user install instead of using a venv:

```bash
python3.11 -m pip uninstall -y ollabridge
rm -f ~/.local/bin/ollabridge ~/.local/bin/ollabridge-node ~/.local/bin/ollabridge-mcp
rm -rf ~/.local/lib/python3.11/site-packages/ollabridge
rm -rf ~/.local/lib/python3.11/site-packages/ollabridge-*.dist-info
python3.11 -m pip install --user --no-cache-dir --force-reinstall ollabridge
hash -r
python3.11 -c "import ollabridge; print(ollabridge.__file__)"
~/.local/bin/ollabridge --help
```

---

## 🔧 Configuration

### Create `.env` file

```bash
make env
```

This creates `.env` from `.env.example`. Edit it with your settings:

```env
# API Keys (comma-separated for multiple keys)
API_KEYS=sk-ollabridge-your-key-here

# Ollama connection
OLLAMA_BASE_URL=http://localhost:11434

# Default models
DEFAULT_MODEL=deepseek-r1
DEFAULT_EMBED_MODEL=nomic-embed-text

# Rate limiting
RATE_LIMIT=60/minute

# Server
HOST=0.0.0.0
PORT=11435

# Database (optional - defaults to SQLite)
# DATABASE_URL=postgresql://user:pass@localhost/ollabridge
```

### Auto-generated API key

OllaBridge auto-generates a secure API key on first run. Check `.env` after starting:

```bash
make start
# Check generated key in .env
cat .env | grep API_KEYS
```

---

## 🚀 Running OllaBridge

### Standard mode

```bash
make start
```

Or directly:
```bash
ollabridge start
```

### Development mode (auto-reload)

```bash
make dev
```

### With public URL (ngrok tunnel)

```bash
make start-share
```

Or:
```bash
ollabridge start --share
```

### MCP server mode

```bash
make mcp
```

Or:
```bash
ollabridge-mcp
```

---

## 📊 Makefile Commands Reference

### Installation

| Command | Description |
|---------|-------------|
| `make install` | Install OllaBridge (ultra-fast with uv) |
| `make install-dev` | Install with dev dependencies |
| `make install-pip` | Install with pip (fallback) |
| `make install-uv` | Install uv package manager |
| `make upgrade` | Upgrade all dependencies |

### Development

| Command | Description |
|---------|-------------|
| `make dev` | Start in development mode (auto-reload) |
| `make start` | Start OllaBridge gateway |
| `make start-share` | Start with public URL (tunnel) |
| `make mcp` | Start MCP server |
| `make env` | Create .env from example |
| `make logs` | View recent request logs |

### Testing & Quality

| Command | Description |
|---------|-------------|
| `make test` | Run all tests |
| `make test-cov` | Run tests with coverage |
| `make test-watch` | Run tests in watch mode |
| `make format` | Format code (black + ruff) |
| `make lint` | Check code quality |
| `make type` | Run type checking |
| `make check` | Run all quality checks |

### Build & Publish

| Command | Description |
|---------|-------------|
| `make build` | Build distribution packages |
| `make publish` | Publish to PyPI |
| `make publish-test` | Publish to TestPyPI |
| `make clean` | Clean build artifacts |

### Utilities

| Command | Description |
|---------|-------------|
| `make version` | Show OllaBridge version |
| `make info` | Show system information |
| `make docs` | Open documentation |
| `make help` | Show all commands |

---

## 🐍 Python Version Requirements

- **Minimum:** Python 3.10
- **Recommended:** Python 3.11 or 3.12
- **Tested on:** 3.10, 3.11, 3.12

Check your Python version:
```bash
python3 --version
```

---

## 📦 Dependencies

### Core Dependencies

Installed automatically:
- `fastapi>=0.110` - Web framework
- `uvicorn[standard]>=0.27` - ASGI server
- `httpx>=0.26` - Async HTTP client
- `typer>=0.12` - CLI framework
- `rich>=13.7` - Terminal formatting
- `pydantic>=2.6` - Data validation
- `sqlmodel` - Database ORM
- `slowapi` - Rate limiting
- `tenacity>=8.2` - Retry logic

### Development Dependencies

Install with `make install-dev`:
- `pytest>=7.4` - Testing framework
- `pytest-cov>=4.1` - Coverage reporting
- `black>=23.7` - Code formatter
- `ruff>=0.0.280` - Fast linter
- `mypy>=1.4` - Type checker

---

## 🔍 Verification

After installation, verify everything works:

```bash
# Check OllaBridge is installed
ollabridge --help

# Check version
make version

# Run tests (dev install only)
make test

# Start the gateway
make start
```

You should see:
```
╭─────────────────── 🚀 Gateway Ready ────────────────────╮
│ ✅ OllaBridge is Online                                  │
│ Model:        deepseek-r1                                │
│ Local API:    http://localhost:11435/v1                 │
│ Health:       http://localhost:11435/health             │
│ Key:          sk-ollabridge-xxxxx                        │
╰──────────────────────────────────────────────────────────╯
```

---

## 🐛 Troubleshooting

### `uv` not found

Install it:
```bash
make install-uv
```

Or manually:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Ollama not installed

OllaBridge will offer to install it automatically when you run `make start`.

Or install manually:
- **Linux:** `curl -fsSL https://ollama.com/install.sh | sh`
- **macOS:** `brew install ollama`, or download from https://ollama.com/download
- **Windows:** Download from https://ollama.com/download

### Linux/WSL: `This version requires zstd for extraction`

Ollama's install script extracts zstd-compressed tarballs, and `zstd` is not
preinstalled on Debian/Ubuntu (including stock WSL images), so the script
aborts:

```
ERROR: This version requires zstd for extraction.
```

OllaBridge now detects this before running the script: it installs the missing
prerequisites (`curl`, `tar`, `zstd`) with your system package manager
(apt-get/dnf/yum/zypper/pacman/apk), then runs the installer — and retries once
if the script still reports a missing `zstd`.

If you prefer to do it yourself:

```bash
sudo apt-get update && sudo apt-get install -y zstd   # Debian/Ubuntu/WSL
sudo dnf install -y zstd                              # RHEL/CentOS/Fedora
sudo pacman -S zstd                                   # Arch
```

Then re-run `ollabridge start`.

### Ollama installed but "not on your PATH"

The install script drops the binary in `/usr/local/bin`, which some non-login
shells (and freshly provisioned WSL distros) leave off `PATH`. OllaBridge still
finds and uses it, but to get the `ollama` command yourself:

```bash
export PATH="/usr/local/bin:$PATH"
```

### Model not found

OllaBridge auto-pulls the default model (`deepseek-r1`) on first run.

To manually pull:
```bash
ollama pull deepseek-r1
```

### Port 11435 already in use

Change the port in `.env`:
```env
PORT=11436
```

Or specify when starting:
```bash
ollabridge start --port 11436
```

### Permission errors

On Linux/macOS, you may need to add execute permissions:
```bash
chmod +x $(which ollabridge)
```

### Import errors

Ensure you're in the correct virtual environment:
```bash
which python3
```

Reinstall:
```bash
make clean
make install-dev
```

---

## 🆘 Getting Help

- **Documentation:** [README.md](README.md)
- **MCP Guide:** [docs/MCP.md](docs/MCP.md)
- **Issues:** https://github.com/ruslanmv/ollabridge/issues
- **Discussions:** https://github.com/ruslanmv/ollabridge/discussions

---

## 🚀 Next Steps

After installation:

1. **Start the gateway:** `make start`
2. **Test with curl:**
   ```bash
   curl http://localhost:11435/health
   ```
3. **Use in your app:**
   ```python
   from openai import OpenAI

   client = OpenAI(
       base_url="http://localhost:11435/v1",
       api_key="your-key-from-env"
   )
   ```

**Happy coding!** 🎉
