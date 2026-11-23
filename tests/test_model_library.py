"""Tests for the model library: search, sizes, and the opt-in "fits this PC" list.

No network: HTTP goes through ``httpx.MockTransport`` and the hardware is a
plain dict. The data directory is a temp folder (``OLLABRIDGE_HOME``).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ollabridge.addons.local_catalog import fit, library, library_routes  # noqa: E402
from ollabridge.addons.local_catalog.pulls import LocalPullManager  # noqa: E402
from ollabridge.addons.local_catalog.repository import LocalCatalogRepository  # noqa: E402
from ollabridge.core.security import require_api_key  # noqa: E402


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLABRIDGE_HOME", str(tmp_path))
    monkeypatch.delenv("OBRIDGE_FITLAB_RECOMMENDATIONS", raising=False)
    monkeypatch.delenv("OBRIDGE_FITLAB_REGISTRY_URL", raising=False)


# ── Ollama library search ───────────────────────────────────────────────

# As the live page writes it, double space after `<span` included.
CHIP = '<span  class="inline-flex items-center rounded-md bg-[#ddf4ff] px-2 py-0.5 text-xs">{}</span>'
SEARCH_PAGE = f"""
<ul>
<li class="border-t">
  <a href="/library/qwen2.5" class="group grid">
    <h2 title="qwen2.5"><span>qwen2.5</span></h2>
    <span title="Updated September 19, 2024">2y</span>
    <div>{CHIP.format("tools")}</div>
    <p class="mt-1">Qwen2.5 models are pretrained on Alibaba&#39;s latest dataset.</p>
    <div>
      <span title="46,087,015 downloads"><span>46.1M</span></span>
      <span><span>133 tags</span></span>
      {CHIP.format("0.5b")} {CHIP.format("7b")} {CHIP.format("72b")}
    </div>
  </a>
</li>
<li class="border-t">
  <a href="/someone/tiny-model" class="group grid"><h2><span>tiny-model</span></h2></a>
</li>
<li><a href="/privacy">Privacy</a></li>
</ul>
"""


def test_search_page_is_parsed_into_cards():
    cards = library.parse_search_html(SEARCH_PAGE)
    assert [c["name"] for c in cards] == ["qwen2.5", "someone/tiny-model"]  # the footer link is not a model
    qwen = cards[0]
    assert qwen["sizes"] == ["0.5b", "7b", "72b"]
    assert qwen["capabilities"] == ["tools"]
    assert qwen["downloads"] == 46_087_015
    assert qwen["tag_count"] == 133
    assert qwen["updated"] == "September 19, 2024"
    assert qwen["description"] == "Qwen2.5 models are pretrained on Alibaba's latest dataset."


def test_an_unknown_page_layout_gives_no_results_not_an_error():
    assert library.parse_search_html("<html><body>redesigned</body></html>") == []


def test_names_that_could_escape_the_registry_path_are_refused():
    assert library.valid_name("qwen2.5")
    assert library.valid_name("someone/tiny-model")
    for bad in ("", "../etc", "a/b/c", "qwen 2.5", "http://x", "a:b"):
        assert not library.valid_name(bad)
    assert library.valid_hf_repo("bartowski/Llama-3.2-3B-Instruct-GGUF")
    assert not library.valid_hf_repo("no-owner")
    assert not library.valid_hf_repo("a/b/c")


def test_search_is_cached_and_tag_sizes_tolerate_a_missing_tag():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "ollama.com":
            return httpx.Response(200, text=SEARCH_PAGE)
        if request.url.path.endswith("/manifests/7b"):
            assert request.url.path == "/v2/library/qwen2.5/manifests/7b"
            return httpx.Response(200, json={"config": {"size": 500}, "layers": [{"size": 4_000}, {"size": 700}]})
        if request.url.path.endswith("/manifests/14b"):
            return httpx.Response(429)  # a rate limit is not "this model does not exist"
        return httpx.Response(404)

    lib = library.OllamaLibrary(transport=httpx.MockTransport(handler))

    async def run():
        first = await lib.search("Qwen")
        second = await lib.search("  qwen ")  # same query, normalised
        sizes = await lib.tag_sizes("qwen2.5", ["7b", "14b", "999b"])
        again = await lib.tag_sizes("qwen2.5", ["7b"])  # answered from the cache
        return first, second, sizes, again

    first, second, sizes, again = asyncio.run(run())
    assert first == second and len([c for c in calls if "ollama.com" in c]) == 1
    assert sizes == [
        {"tag": "7b", "ref": "qwen2.5:7b", "size_bytes": 5_200, "available": True},
        {"tag": "14b", "ref": "qwen2.5:14b", "size_bytes": None, "available": True},  # kept, size unknown
        {"tag": "999b", "ref": "qwen2.5:999b", "size_bytes": None, "available": False},
    ]
    assert again == sizes[:1] and len([c for c in calls if c.endswith("/manifests/7b")]) == 1


# ── Hugging Face GGUF builds ────────────────────────────────────────────


def test_hugging_face_builds_become_pull_references():
    siblings = [
        {"rfilename": "README.md", "size": 10},
        {"rfilename": "Model-Q8_0.gguf", "size": 3_400},
        {"rfilename": "Model-Q4_K_M.gguf", "size": 2_000},
        {"rfilename": "Model-IQ1_S.gguf", "size": 900},
        {"rfilename": "mmproj-Model-F16.gguf", "size": 600},  # a vision projector, not a model
        {"rfilename": "Model-Q6_K-00001-of-00002.gguf", "size": 5_000},  # split: not installable
    ]
    builds = library.gguf_quantizations(siblings, "owner/Model-GGUF")
    assert [b["tag"] for b in builds] == ["Q4_K_M", "Q8_0", "IQ1_S"]  # the usual default first
    assert builds[0] == {
        "tag": "Q4_K_M", "ref": "hf.co/owner/Model-GGUF:Q4_K_M", "size_bytes": 2_000, "available": True,
    }


def test_hugging_face_search_keeps_public_gguf_repositories():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["filter"] == "gguf" and request.url.params["search"] == "llama"
        return httpx.Response(200, json=[
            {"id": "owner/Llama-GGUF", "downloads": 9, "likes": 3, "pipeline_tag": "text-generation"},
            {"id": "owner/secret", "private": True},
            {"id": "not a repo id"},
        ])

    hub = library.HuggingFaceLibrary(transport=httpx.MockTransport(handler))
    results = asyncio.run(hub.search("llama"))
    assert [r["name"] for r in results] == ["owner/Llama-GGUF"]
    assert results[0]["downloads"] == 9 and results[0]["likes"] == 3


# ── "Fits this PC" ─────────────────────────────────────────────────────

ARCH = {"n_layers": 42, "n_kv_heads": 2, "head_dim": 128}


def _model(tag, params_b, likes, **extra):
    return {"id": tag, "ollama_tag": tag, "params_b": params_b, "arch": ARCH, "hf_stats": {"likes": likes}, **extra}


def test_estimate_matches_the_fitlab_registry_number():
    # FitLab publishes est_vram_gb 2.5 for this 2B model at Q4_K_M / 8K context.
    model = {"params_b": 2.0, "arch": ARCH}
    assert fit.estimate(model, 12.0) == {"est_gb": 2.5, "verdict": "fits"}
    assert fit.estimate(model, 2.6)["verdict"] == "tight"
    assert fit.estimate(model, 2.0)["verdict"] == "offload"
    assert fit.estimate(model, 1.0)["verdict"] == "no"


def test_recommendations_are_the_models_that_fit_most_liked_first():
    registry = {"models": {
        "small": _model("small:2b", 2.0, likes=10),
        "liked": _model("liked:4b", 4.0, likes=900),
        "huge": _model("huge:70b", 70.0, likes=5000),          # does not fit 6 GB
        "stale": _model("stale:2b", 2.0, likes=9999, status="stale"),
        "no_tag": {**_model("x", 2.0, likes=9999), "ollama_tag": None},
        "broken": {"ollama_tag": "broken:1b", "params_b": 1.0},  # no arch: skipped, not fatal
    }}
    rows = fit.recommend(registry, {"budget_gb": 6.0})
    assert [r["ollama_tag"] for r in rows] == ["liked:4b", "small:2b"]
    assert rows[0]["verdict"] == "fits" and rows[0]["likes"] == 900
    assert fit.recommend(registry, {"budget_gb": 0}) == []


def test_recommendations_are_off_until_the_user_turns_them_on():
    assert fit.is_enabled() is False
    fit.set_enabled(True)
    assert fit.is_enabled() is True
    fit.set_enabled(False)
    assert fit.is_enabled() is False


def test_registry_is_downloaded_once_then_served_from_the_cache():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(503)  # the first mirror is down: the next one is tried
        return httpx.Response(200, json={"generated_at": "2026-10-25", "models": {"a": {}}})

    transport = httpx.MockTransport(handler)
    registry, source = asyncio.run(fit.load_registry(transport=transport))
    assert source == "live" and registry["generated_at"] == "2026-10-25" and len(calls) == 2
    _, source = asyncio.run(fit.load_registry(transport=transport))
    assert source == "cache" and len(calls) == 2


# ── Routes ─────────────────────────────────────────────────────────────


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(library_routes.router)
    app.dependency_overrides[require_api_key] = lambda: "test"
    return TestClient(app)


def test_recommendations_route_does_nothing_while_off(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("nothing may be probed or downloaded while recommendations are off")

    monkeypatch.setattr(fit, "detect_hardware", boom)
    monkeypatch.setattr(fit, "load_registry", boom)
    assert client.get("/local/library/recommendations").json() == {"enabled": False}


def test_recommendations_route_once_enabled(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def registry(**_kwargs):
        return {"generated_at": "2026-10-25", "models": {"m": _model("liked:4b", 4.0, likes=7)}}, "live"

    monkeypatch.setattr(fit, "detect_hardware", lambda: {"kind": "nvidia", "name": "GPU", "budget_gb": 6.0})
    monkeypatch.setattr(fit, "load_registry", registry)
    assert client.put("/local/library/recommendations", json={"enabled": True}).json() == {"enabled": True}
    body = client.get("/local/library/recommendations").json()
    assert body["enabled"] is True
    assert [m["ollama_tag"] for m in body["models"]] == ["liked:4b"]
    assert body["hardware"]["name"] == "GPU"
    assert body["registry"] == {"generated_at": "2026-10-25", "source": "live"}


def test_tags_route_rejects_bad_names(client: TestClient):
    assert client.get("/local/library/tags", params={"name": "../x"}).status_code == 422
    assert client.get("/local/library/tags", params={"name": "qwen2.5", "tags": "7b,../x"}).status_code == 422
    assert client.get("/local/library/tags", params={"name": "nope", "source": "huggingface"}).status_code == 422


# ── Download progress ───────────────────────────────────────────────────


class _FakeRuntime:
    def __init__(self, events):
        self._events = events

    async def pull_stream(self, _model):
        for event in self._events:
            yield event


def test_pull_progress_is_the_sum_of_a_models_files(tmp_path: Path):
    events = [
        {"status": "pulling manifest"},
        {"status": "pulling aaa", "digest": "sha256:aaa", "total": 1000, "completed": 1000},
        {"status": "pulling bbb", "digest": "sha256:bbb", "total": 100, "completed": 40},
    ]

    async def run():
        manager = LocalPullManager(LocalCatalogRepository(path=tmp_path / "cat.yaml"))
        progress = await manager.start(node_id="local", external_model_id="m:1", client=_FakeRuntime(events))
        await manager._tasks[("local", "m:1")]
        return progress

    progress = asyncio.run(run())
    # The second file starting must not reset the bar: 1040 of 1100, not 40 of 100.
    assert (progress.completed_bytes, progress.total_bytes) == (1040, 1100)
    assert progress.detail == "downloading"
