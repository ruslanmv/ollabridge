# OllaBridge Tests

This directory contains tests for OllaBridge.

## Test Structure

```
tests/
├── unit/               # Unit tests (fast, no dependencies)
├── integration/        # Integration tests (require Ollama)
└── README.md          # This file
```

## Running Tests

### Quick Start

```bash
# Run unit tests only (fast, no Ollama required)
make test

# Run all tests (unit + integration, requires Ollama)
make test-all

# Run integration tests only
make test-integration

# Run with coverage
make test-cov
```

### Direct pytest Commands

```bash
# Unit tests only
pytest tests/ -v --ignore=tests/integration/

# All tests
pytest tests/ -v

# Integration tests only
pytest tests/integration/ -v -s

# With coverage
pytest tests/ --cov=src/ollabridge --cov-report=html
```

## Integration Tests

Integration tests require:

1. **Ollama installed and running**
   ```bash
   # Install Ollama
   curl -fsSL https://ollama.com/install.sh | sh

   # Start Ollama server
   ollama serve
   ```

2. **A model pulled**
   ```bash
   # Pull a lightweight model
   ollama pull tinyllama
   ```

3. **Run the integration tests**
   ```bash
   make test-integration
   ```

### What Integration Tests Check

- ✅ OllaBridge health endpoint
- ✅ Hello world chat completion
- ✅ Simple Q&A (math test)
- ✅ Embeddings generation
- ✅ Unauthorized access rejection
- ✅ Invalid model handling

### Environment Variables

```bash
# Customize test configuration
export OLLAMA_BASE_URL="http://localhost:11434"
export DEFAULT_MODEL="tinyllama"
export OLLABRIDGE_PORT="11435"

# Run tests
make test-integration
```

## CI/CD

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs:

1. **Unit tests** - Fast tests without Ollama
2. **Integration tests** - Full tests with Ollama
3. **Smoke test** - Quick hello world verification

## Writing Tests

### Unit Tests

Put unit tests in `tests/` (root level). They should:
- Be fast (< 1s per test)
- Not require external services
- Mock external dependencies

Example:
```python
def test_something():
    assert True
```

### Integration Tests

Put integration tests in `tests/integration/`. They should:
- Test real Ollama integration
- Use fixtures for setup/teardown
- Skip if Ollama unavailable

Example:
```python
import pytest

@pytest.fixture
def check_ollama():
    # Check Ollama is available
    ...

def test_real_query(check_ollama):
    # Test with real Ollama
    ...
```

## Troubleshooting

### "Ollama not available"

1. Check Ollama is running:
   ```bash
   curl http://localhost:11434/api/tags
   ```

2. Start Ollama:
   ```bash
   ollama serve
   ```

### "Model not found"

Pull the test model:
```bash
ollama pull tinyllama
```

### Integration tests hanging

Increase timeout or use a faster model:
```bash
export DEFAULT_MODEL="tinyllama"  # Smallest, fastest model
make test-integration
```

### Port conflicts

Change the test port:
```bash
export OLLABRIDGE_PORT="11436"
make test-integration
```

## Performance

- **Unit tests:** ~1-5 seconds
- **Integration tests:** ~30-60 seconds (depends on model)
- **Full suite:** ~1-2 minutes

## Best Practices

1. **Run unit tests frequently** during development
2. **Run integration tests** before commits
3. **Run full suite** before PRs
4. **Use fast models** for CI (tinyllama, gemma:2b)
5. **Mock when possible** to keep tests fast

---

For more information, see the main [README.md](../README.md).
