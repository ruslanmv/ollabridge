# Contributing to OllaBridge

Thank you for considering contributing to OllaBridge! 🎉

We welcome contributions from the community and are excited to see what you'll bring to the project.

## How to Contribute

### Reporting Bugs

If you find a bug, please open an issue on GitHub with:

1. A clear, descriptive title
2. Steps to reproduce the issue
3. Expected behavior vs actual behavior
4. Your environment (OS, Python version, OllaBridge version)
5. Any relevant logs or error messages

### Suggesting Features

Feature requests are welcome! Please open an issue with:

1. A clear description of the feature
2. Why it would be useful
3. Any examples or use cases

### Pull Requests

We actively welcome pull requests:

1. **Fork the repo** and create your branch from `main`
2. **Make your changes** and add tests if applicable
3. **Ensure tests pass** by running `pytest`
4. **Follow the code style** (we use `black` and `ruff`)
5. **Write a clear commit message** describing your changes
6. **Open a PR** with a clear description

#### Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/ollabridge.git
cd ollabridge

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/
ruff check src/ --fix
```

#### Code Style

- We use **Black** for code formatting
- We use **Ruff** for linting
- Type hints are encouraged
- Docstrings should follow Google style

#### Testing

- Add tests for new features
- Ensure existing tests pass
- Aim for >80% code coverage

```bash
# Run tests with coverage
pytest --cov=ollabridge --cov-report=html
```

## Priority Areas for Contribution

We're especially interested in contributions for:

### 🔌 Provider Adapters
- LM Studio integration
- llama.cpp support
- vLLM support
- LocalAI support

### 🌐 Tunneling/Sharing
- Cloudflare Tunnel helpers
- Tailscale integration
- Better ngrok integration

### 🔄 Streaming
- Full OpenAI streaming support
- Server-sent events (SSE) implementation

### 🔒 Security
- IP allowlisting
- Request signing
- OAuth/OIDC support
- Rate limiting improvements

### 📊 Observability
- Prometheus metrics
- OpenTelemetry support
- Better logging
- Admin dashboard

### 🧪 Testing
- Integration tests
- End-to-end tests
- Performance benchmarks

## Code of Conduct

### Our Standards

- Be respectful and inclusive
- Welcome newcomers
- Accept constructive criticism gracefully
- Focus on what's best for the community

### Unacceptable Behavior

- Harassment, discrimination, or trolling
- Personal attacks or insults
- Publishing others' private information
- Other conduct inappropriate in a professional setting

## Questions?

Feel free to:

- Open an issue for questions
- Start a discussion on GitHub Discussions
- Reach out to the maintainers

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

**Thank you for making OllaBridge better!** 🚀
