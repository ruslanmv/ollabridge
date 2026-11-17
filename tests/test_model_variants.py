"""Model copies (``/local/variants``): the "Build a model" wizard's backend.

The promises: a copy is made from an installed model with no download, its
name is made for the user, an original can never be removed by mistake, and
"loads here" is a measured answer in words a person can act on.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from ollabridge.addons.local_catalog import variants
from ollabridge.core import runtime_settings as rts
from ollabridge.core.settings import settings

AUTH = {"Authorization": "Bearer test-key-abc"}
URL = "http://localhost:11434"
OOM = "llama-server process has terminated: exit status 0xc0000409: GGML_ASSERT(ctx->mem_buffer != NULL) failed"


class FakeOllama:
    """Just enough of Ollama: tags, show, create, delete, ps and the three ways to load a model."""

    def __init__(self) -> None:
        self.models: dict[str, dict] = {
            "clef-flash:9b": {
                "size": 10_600_000_000,
                "parent": "clef-flash:9b-q8_0",
                "num_ctx": 16384,
                "capabilities": ["decision", "vision"],
                "max_context": 262144,
            },
            "qwen2.5:1.5b": {
                "size": 1_000_000_000,
                "parent": "",
                "num_ctx": None,
                "capabilities": ["completion", "tools"],
                "max_context": 32768,
            },
            "nomic-embed-text:latest": {
                "size": 270_000_000,
                "parent": "",
                "num_ctx": None,
                "capabilities": ["embedding"],
                "max_context": 2048,
            },
        }
        #: Contexts above this do not fit in memory.
        self.fits_up_to = 6144
        self.requests: list[tuple[str, str, dict]] = []
        self.loaded: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.requests.append((request.method, path, body))
        if path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": n, "size": m["size"]} for n, m in self.models.items()]}
            )
        if path == "/api/show":
            model = self._get(body["model"])
            if model is None:
                return httpx.Response(404, json={"error": "model not found"})
            parameters = f"num_ctx                        {model['num_ctx']}" if model["num_ctx"] else ""
            return httpx.Response(
                200,
                json={
                    "details": {
                        "parent_model": model["parent"],
                        "parameter_size": "9.1B",
                        "quantization_level": "Q8_0",
                    },
                    "parameters": parameters,
                    "capabilities": model["capabilities"],
                    "model_info": {"clef.context_length": model["max_context"]},
                },
            )
        if path == "/api/create":
            source = self._get(body["from"])
            name = body["model"] if ":" in body["model"] else f"{body['model']}:latest"
            self.models[name] = {**source, "parent": body["from"], "num_ctx": body["parameters"]["num_ctx"]}
            return httpx.Response(200, json={"status": "success"})
        if path == "/api/delete":
            name = next(n for n in self.models if variants.normalize(n) == variants.normalize(body["model"]))
            del self.models[name]
            return httpx.Response(200, json={})
        if path == "/api/ps":
            models = (
                [{"name": self.loaded, "size": 11_900_000_000, "size_vram": 3_500_000_000}] if self.loaded else []
            )
            return httpx.Response(200, json={"models": models})
        if path in ("/v1/systemone", "/api/generate", "/api/embed"):
            model = self._get(body["model"])
            if (model["num_ctx"] or 4096) > self.fits_up_to:
                return httpx.Response(500, json={"error": OOM})
            self.loaded = next(n for n in self.models if variants.normalize(n) == variants.normalize(body["model"]))
            return httpx.Response(200, json={"answers": {}})
        return httpx.Response(404, json={"error": f"unexpected {path}"})

    def _get(self, name: str) -> dict | None:
        wanted = variants.normalize(name)
        return next((m for n, m in self.models.items() if variants.normalize(n) == wanted), None)

    def calls(self, path: str) -> list[dict]:
        return [body for _method, p, body in self.requests if p == path]


@pytest.fixture
def ollama(tmp_path, monkeypatch):
    fake = FakeOllama()
    monkeypatch.setenv("OLLABRIDGE_HOME", str(tmp_path))
    monkeypatch.setattr(rts, "_STORE_FILE", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(rts, "_cache", None)
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", URL)
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")
    monkeypatch.setattr(variants, "_transport", httpx.MockTransport(fake.handler))
    yield fake
    monkeypatch.setattr(rts, "_cache", None)


@pytest.fixture
def client(ollama):
    from ollabridge.api.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _rows(client) -> dict[str, dict]:
    r = client.get("/local/variants", headers=AUTH)
    assert r.status_code == 200, r.text
    return {row["name"]: row for row in r.json()["models"]}


# --- names -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "context", "name"),
    [
        ("clef-flash:9b", 6144, "clef-flash-6k"),
        ("clef-flash:9b", 8192, "clef-flash-8k"),
        ("clef-flash-8k", 4096, "clef-flash-4k"),  # a copy's own size is replaced, not stacked
        ("qwen2.5:1.5b", 5000, "qwen2.5-5000"),
        ("hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M", 16384, "Llama-3.2-3B-Instruct-GGUF-16k"),
    ],
)
def test_the_name_is_made_from_the_model_and_the_size(source, context, name):
    assert variants.suggest_name(source, context) == name
    assert variants.valid_name(name)


def test_the_next_smaller_size_is_offered_after_a_failure():
    assert variants.smaller_context(8192) == 6144
    assert variants.smaller_context(7000) == 6144
    assert variants.smaller_context(2048) is None
    assert variants.smaller_context(None) is None


@pytest.mark.parametrize(
    "error",
    [
        OOM,
        "llama-server reported out-of-memory during startup: cudaMalloc failed: out of memory",
        "model requires more system memory (11.2 GiB) than is available (6.4 GiB)",
    ],
)
def test_a_memory_failure_is_said_in_plain_words(error):
    assert variants.explain_failure(error) == "Not enough free memory to load it."


def test_another_failure_keeps_the_runtimes_first_line():
    assert variants.explain_failure("unsupported architecture\nstack...") == "unsupported architecture"


# --- list ------------------------------------------------------------------


def test_the_list_says_what_each_model_is(client):
    rows = _rows(client)
    clef = rows["clef-flash:9b"]
    assert clef["built_from"] == "clef-flash:9b-q8_0"
    assert clef["is_copy"] is False  # its parent is a library build that is not installed
    assert clef["context"] == 16384
    assert clef["max_context"] == 262144
    assert clef["kind"] == "decision"
    assert clef["load"] is None
    assert rows["qwen2.5:1.5b"]["context"] is None
    assert rows["qwen2.5:1.5b"]["kind"] == "chat"
    assert rows["nomic-embed-text"]["kind"] == "embedding"


def test_copies_follow_the_model_they_were_built_from(client):
    for context in (8192, 4096):
        client.post("/local/variants", json={"source": "clef-flash:9b", "context": context}, headers=AUTH)
    names = [row["name"] for row in client.get("/local/variants", headers=AUTH).json()["models"]]
    assert names[:3] == ["clef-flash:9b", "clef-flash-4k", "clef-flash-8k"]


def test_ollama_down_is_a_502(client, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(variants, "_transport", httpx.MockTransport(refuse))
    r = client.get("/local/variants", headers=AUTH)
    assert r.status_code == 502
    assert URL in r.json()["detail"]


def test_the_api_key_is_required(client):
    assert client.get("/local/variants").status_code == 401
    assert client.post("/local/variants", json={"source": "clef-flash:9b", "context": 4096}).status_code == 401
    assert client.post("/local/variants/test", json={"name": "clef-flash:9b"}).status_code == 401
    assert client.delete("/local/variants/clef-flash-6k").status_code == 401


# --- create ----------------------------------------------------------------


def test_a_copy_is_created_with_a_generated_name(client, ollama):
    r = client.post("/local/variants", json={"source": "clef-flash:9b", "context": 6144}, headers=AUTH)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["name"] == "clef-flash-6k"
    assert row["built_from"] == "clef-flash:9b"
    assert row["is_copy"] is True
    assert row["context"] == 6144
    assert ollama.calls("/api/create") == [
        {"model": "clef-flash-6k", "from": "clef-flash:9b", "parameters": {"num_ctx": 6144}, "stream": False}
    ]


def test_a_copy_of_a_copy_is_built_on_the_original(client, ollama):
    client.post("/local/variants", json={"source": "clef-flash:9b", "context": 8192}, headers=AUTH)
    r = client.post("/local/variants", json={"source": "clef-flash-8k", "context": 4096}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "clef-flash-4k"
    assert r.json()["built_from"] == "clef-flash:9b"
    assert ollama.calls("/api/create")[-1]["from"] == "clef-flash:9b"


def test_a_given_name_is_used(client):
    r = client.post(
        "/local/variants", json={"source": "qwen2.5:1.5b", "context": 8192, "name": "support-bot"}, headers=AUTH
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "support-bot"


@pytest.mark.parametrize(
    ("body", "status", "fragment"),
    [
        ({"source": "missing-model", "context": 4096}, 404, "not installed"),
        ({"source": "clef-flash:9b", "context": 16384, "name": "qwen2.5:1.5b"}, 409, "already exists"),
        ({"source": "clef-flash:9b", "context": 4096, "name": "bad name!"}, 400, "letters"),
        ({"source": "qwen2.5:1.5b", "context": 65536}, 400, "at most 32,768"),
    ],
)
def test_a_refused_copy_says_why_and_creates_nothing(client, ollama, body, status, fragment):
    r = client.post("/local/variants", json=body, headers=AUTH)
    assert r.status_code == status, r.text
    assert fragment in r.json()["detail"]
    assert ollama.calls("/api/create") == []


def test_an_existing_copy_is_never_overwritten(client, ollama):
    body = {"source": "clef-flash:9b", "context": 6144}
    assert client.post("/local/variants", json=body, headers=AUTH).status_code == 200
    assert client.post("/local/variants", json=body, headers=AUTH).status_code == 409
    assert len(ollama.calls("/api/create")) == 1


# --- load test -------------------------------------------------------------


def test_a_model_that_fits_is_recorded_with_its_memory(client, ollama):
    client.post("/local/variants", json={"source": "clef-flash:9b", "context": 6144}, headers=AUTH)
    r = client.post("/local/variants/test", json={"name": "clef-flash-6k"}, headers=AUTH)
    assert r.status_code == 200, r.text
    load = r.json()["load"]
    assert load["loads"] is True
    assert load["total_bytes"] == 11_900_000_000
    assert load["gpu_bytes"] == 3_500_000_000
    assert load["reason"] is None and load["try_context"] is None
    # The result is kept and shown in the list.
    assert _rows(client)["clef-flash-6k"]["load"]["loads"] is True


def test_a_model_that_does_not_fit_says_so_and_offers_a_smaller_size(client, ollama):
    client.post("/local/variants", json={"source": "clef-flash:9b", "context": 8192}, headers=AUTH)
    r = client.post("/local/variants/test", json={"name": "clef-flash-8k"}, headers=AUTH)
    assert r.status_code == 200, r.text
    load = r.json()["load"]
    assert load["loads"] is False
    assert load["reason"] == "Not enough free memory to load it."
    assert load["try_context"] == 6144
    assert load["total_bytes"] is None


def test_each_kind_of_model_is_loaded_its_own_way(client, ollama):
    for name in ("clef-flash:9b", "qwen2.5:1.5b", "nomic-embed-text"):
        ollama.fits_up_to = 1_000_000
        assert client.post("/local/variants/test", json={"name": name}, headers=AUTH).status_code == 200
    assert [b["model"] for b in ollama.calls("/v1/systemone")] == ["clef-flash:9b"]
    assert [b["model"] for b in ollama.calls("/api/generate")] == ["qwen2.5:1.5b"]
    assert [b["model"] for b in ollama.calls("/api/embed")] == ["nomic-embed-text"]


def test_a_new_copy_starts_untested_even_if_the_name_was_tested_before(client, ollama):
    body = {"source": "clef-flash:9b", "context": 6144}
    client.post("/local/variants", json=body, headers=AUTH)
    client.post("/local/variants/test", json={"name": "clef-flash-6k"}, headers=AUTH)
    assert client.delete("/local/variants/clef-flash-6k", headers=AUTH).status_code == 200
    assert client.post("/local/variants", json=body, headers=AUTH).json()["load"] is None


def test_testing_a_model_that_is_not_installed_is_a_404(client):
    r = client.post("/local/variants/test", json={"name": "missing-model"}, headers=AUTH)
    assert r.status_code == 404


# --- remove ----------------------------------------------------------------


def test_a_copy_can_be_removed(client, ollama):
    client.post("/local/variants", json={"source": "clef-flash:9b", "context": 6144}, headers=AUTH)
    assert client.delete("/local/variants/clef-flash-6k", headers=AUTH).status_code == 200
    assert "clef-flash-6k" not in _rows(client)
    assert "clef-flash:9b" in _rows(client)


def test_an_original_is_never_removed(client, ollama):
    r = client.delete("/local/variants/clef-flash:9b", headers=AUTH)
    assert r.status_code == 400
    assert "not a copy" in r.json()["detail"]
    assert ollama.calls("/api/delete") == []
