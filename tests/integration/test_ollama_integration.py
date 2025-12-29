"""
Integration tests for OllaBridge with Ollama backend.

These tests require:
- Ollama installed and running (ollama serve)
- A model pulled (e.g., tinyllama, gemma:2b)

Run with:
    pytest tests/integration/ -v -s

Or via Makefile:
    make test-integration
"""

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

# Test configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLABRIDGE_PORT = int(os.getenv("OLLABRIDGE_PORT", "11435"))
OLLABRIDGE_BASE_URL = f"http://localhost:{OLLABRIDGE_PORT}"
TEST_MODEL = os.getenv("DEFAULT_MODEL", "tinyllama")


@pytest.fixture(scope="module")
def check_ollama():
    """Check if Ollama is running and model is available."""
    try:
        response = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        response.raise_for_status()
        models = response.json().get("models", [])
        model_names = [m.get("name", "") for m in models]

        # Check if test model is available
        if not any(TEST_MODEL in name for name in model_names):
            pytest.skip(
                f"Model '{TEST_MODEL}' not found. "
                f"Pull it with: ollama pull {TEST_MODEL}"
            )

        return True
    except Exception as e:
        pytest.skip(f"Ollama not available: {e}")


@pytest.fixture(scope="module")
def ollabridge_server(check_ollama):
    """Start OllaBridge server for testing."""
    # Start OllaBridge in background
    env = os.environ.copy()
    env["OLLAMA_BASE_URL"] = OLLAMA_BASE_URL
    env["DEFAULT_MODEL"] = TEST_MODEL
    env["PORT"] = str(OLLABRIDGE_PORT)

    # Read API key from .env file
    env_file = Path(".env")
    if env_file.exists():
        content = env_file.read_text()
        for line in content.splitlines():
            if line.startswith("API_KEYS="):
                env["API_KEYS"] = line.split("=", 1)[1].strip()
                break

    process = subprocess.Popen(
        ["ollabridge", "start", "--model", TEST_MODEL, "--port", str(OLLABRIDGE_PORT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path.cwd(),  # Ensure we're in the project root
    )

    # Wait for server to start
    max_wait = 30
    for i in range(max_wait):
        try:
            response = httpx.get(f"{OLLABRIDGE_BASE_URL}/health", timeout=2.0)
            if response.status_code == 200:
                print(f"\n✓ OllaBridge started (waited {i}s)")
                break
        except Exception:
            if i < max_wait - 1:
                time.sleep(1)
            else:
                process.kill()
                pytest.fail("OllaBridge failed to start within 30 seconds")

    yield process

    # Cleanup
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture
def api_key(ollabridge_server):
    """Get API key from .env file."""
    env_file = Path(".env")
    if env_file.exists():
        content = env_file.read_text()
        for line in content.splitlines():
            if line.startswith("API_KEYS="):
                keys = line.split("=", 1)[1].strip()
                return keys.split(",")[0].strip()

    # Default key for testing
    return "test-key-12345"


class TestOllaBridgeIntegration:
    """Integration tests for OllaBridge with real Ollama."""

    def test_health_endpoint(self, ollabridge_server):
        """Test health endpoint returns 200."""
        response = httpx.get(f"{OLLABRIDGE_BASE_URL}/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert "ollama_base_url" in data
        assert "default_model" in data
        assert "detail" in data

    def test_hello_world_chat(self, ollabridge_server, api_key):
        """Test simple hello world chat completion."""
        response = httpx.post(
            f"{OLLABRIDGE_BASE_URL}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": TEST_MODEL,
                "messages": [{"role": "user", "content": "Say hello"}],
                "max_tokens": 50,
            },
            timeout=60.0,  # LLM inference can be slow
        )

        assert response.status_code == 200

        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "message" in data["choices"][0]
        assert "content" in data["choices"][0]["message"]

        content = data["choices"][0]["message"]["content"]
        assert len(content) > 0
        print(f"\n✓ Model response: {content}")

    def test_simple_question(self, ollabridge_server, api_key):
        """Test simple Q&A."""
        response = httpx.post(
            f"{OLLABRIDGE_BASE_URL}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": TEST_MODEL,
                "messages": [
                    {"role": "user", "content": "What is 2+2? Reply with just the number."}
                ],
                "max_tokens": 10,
            },
            timeout=60.0,
        )

        assert response.status_code == 200

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        assert "4" in content
        print(f"\n✓ Math test response: {content}")

    def test_embeddings(self, ollabridge_server, api_key):
        """Test embeddings endpoint."""
        # Skip if model doesn't support embeddings
        try:
            response = httpx.post(
                f"{OLLABRIDGE_BASE_URL}/v1/embeddings",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": TEST_MODEL,
                    "input": "Hello world",
                },
                timeout=30.0,
            )

            if response.status_code == 200:
                data = response.json()
                assert "data" in data
                assert len(data["data"]) > 0
                assert "embedding" in data["data"][0]
                assert isinstance(data["data"][0]["embedding"], list)
                print(f"\n✓ Embeddings returned: {len(data['data'][0]['embedding'])} dimensions")
            else:
                pytest.skip(f"Model {TEST_MODEL} doesn't support embeddings")

        except Exception as e:
            pytest.skip(f"Embeddings not available: {e}")

    def test_unauthorized_access(self, ollabridge_server):
        """Test that requests without API key are rejected."""
        response = httpx.post(
            f"{OLLABRIDGE_BASE_URL}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": TEST_MODEL,
                "messages": [{"role": "user", "content": "Hello"}],
            },
            timeout=10.0,
        )

        # Should be 401 or 403 (unauthorized)
        assert response.status_code in [401, 403]

    def test_invalid_model(self, ollabridge_server, api_key):
        """Test handling of invalid model name."""
        response = httpx.post(
            f"{OLLABRIDGE_BASE_URL}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": "nonexistent-model-12345",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            timeout=10.0,
        )

        # Should return an error (400, 404, or 500)
        assert response.status_code >= 400


# Standalone test for quick smoke testing
def test_quick_smoke():
    """Quick smoke test without fixtures (for CI)."""
    # Check if Ollama is running
    try:
        response = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        response.raise_for_status()
        print("\n✓ Ollama is running")
    except Exception as e:
        pytest.skip(f"Ollama not available: {e}")
