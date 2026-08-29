"""External sources as runtimes: routable locally, published to the cloud.

Two external sources connected in the Sources tab with "Allow this source in
routing" switched on — say Groq serving ``openai/gpt-oss-20b`` and watsonx
serving ``ibm/granite-4-h-small`` — were invisible everywhere that mattered:

* the local seed catalog has no watsonx provider at all, so its model
  resolved to no routing candidate and could not be served;
* ``_inventory()`` enumerated only Ollama and HomePilot, so neither source
  reached Models & Access or the manifest published to OllaBridge Cloud —
  a paired device's model picker showed the 12 local Ollama models and
  nothing else.

These tests pin both halves, and the safety rule that ties them together:
publication follows the routing opt-in the user made on the source.
"""

from __future__ import annotations

import pytest

from ollabridge import model_access as ma
from ollabridge.addons.providers.adapters.groq import GROQ_BASE_URL, GroqAdapter
from ollabridge.addons.providers.adapters.watsonx import WatsonxAdapter
from ollabridge.addons.providers.models import (
    HealthStatus,
    ProviderCategory,
    ProviderConfig,
    ProviderTier,
)
from ollabridge.addons.providers.registry import ProviderRegistry
from ollabridge.addons.providers.router import ProviderRouter
from ollabridge.addons.providers.services import dynamic_source_sync as dss
from ollabridge.providers_meta import ProviderRecord, save_providers

GROQ_MODEL = "openai/gpt-oss-20b"
WATSONX_MODEL = "ibm/granite-4-h-small"
WATSONX_BASE = "https://us-south.ml.cloud.ibm.com"


class _App:
    """Minimal stand-in for the FastAPI app the sync helpers read state off."""

    def __init__(self, registry):
        self.state = type("S", (), {"provider_registry": registry})()


def _seeded_groq() -> ProviderConfig:
    return ProviderConfig(
        id="groq-free",
        name="Groq API",
        kind="groq",
        tier=ProviderTier.MAIN,
        category=ProviderCategory.FREE,
        base_url=GROQ_BASE_URL,
        credential_env="GROQ_API_KEY",
        models=[GROQ_MODEL],
    )


async def _registry_with_seeded_groq() -> ProviderRegistry:
    reg = ProviderRegistry()
    cfg = _seeded_groq()
    await reg.register(cfg, GroqAdapter(base_url=cfg.base_url, api_key=None))
    await reg.update_health(cfg.id, HealthStatus.HEALTHY)
    return reg


def _sources(tmp_path, *records: ProviderRecord, monkeypatch=None):
    """Persist ``providers.yaml`` at *tmp_path* and point the app at it."""
    path = tmp_path / "providers.yaml"
    save_providers(list(records), path)
    if monkeypatch is not None:
        monkeypatch.setattr(
            "ollabridge.core.paths.providers_file", lambda: path, raising=False
        )
    return path


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect providers.yaml and model_access.yaml into a temp directory."""
    monkeypatch.setattr("ollabridge.core.paths.data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "ollabridge.core.paths.providers_file", lambda: tmp_path / "providers.yaml"
    )
    return tmp_path


def _watsonx_source(**over) -> ProviderRecord:
    fields = dict(
        name="watsonx",
        kind="watsonx",
        base_url=WATSONX_BASE,
        default_model=WATSONX_MODEL,
        enabled=True,
        allow_routing=True,
        extra={"project_id": "proj-1"},
    )
    fields.update(over)
    return ProviderRecord(**fields)


# ── A source with no seeded provider becomes its own runtime ─────────


@pytest.mark.asyncio
async def test_a_routing_enabled_source_is_registered_as_a_runtime(isolated_state):
    """watsonx has no entry in the local seed catalog, so without this it is
    'Connected · Routing on' in the UI and serves nothing."""
    reg = await _registry_with_seeded_groq()
    rec = _watsonx_source()
    save_providers([rec])

    assert await dss.sync_byok_runtime(reg, rec, "ibm-cloud-key") is True

    cfg = reg.get_config(dss.byok_provider_id("watsonx"))
    assert cfg is not None
    assert cfg.kind == "watsonx"
    assert cfg.models == [WATSONX_MODEL]
    assert isinstance(reg.get_adapter(cfg.id), WatsonxAdapter)


@pytest.mark.asyncio
async def test_the_registered_runtime_actually_serves_its_model(isolated_state):
    reg = await _registry_with_seeded_groq()
    await dss.sync_byok_runtime(reg, _watsonx_source(), "ibm-cloud-key")
    await reg.update_health(dss.byok_provider_id("watsonx"), HealthStatus.HEALTHY)

    routes = ProviderRouter(reg).resolve(WATSONX_MODEL)
    assert [r.provider_id for r in routes] == ["byok-watsonx"]
    assert routes[0].model == WATSONX_MODEL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override,why",
    [
        ({"allow_routing": False}, "routing is off"),
        ({"enabled": False}, "the source is disabled"),
        ({"default_model": ""}, "no model is selected"),
    ],
)
async def test_a_source_is_not_registered_without_the_opt_in(
    isolated_state, override, why
):
    reg = await _registry_with_seeded_groq()
    rec = _watsonx_source(**override)
    assert await dss.sync_byok_runtime(reg, rec, "ibm-cloud-key") is False, why
    assert reg.get_config(dss.byok_provider_id("watsonx")) is None


@pytest.mark.asyncio
async def test_a_source_without_a_key_is_not_registered(isolated_state):
    reg = await _registry_with_seeded_groq()
    assert await dss.sync_byok_runtime(reg, _watsonx_source(), None) is False
    assert reg.get_config(dss.byok_provider_id("watsonx")) is None


@pytest.mark.asyncio
async def test_switching_routing_off_unregisters_the_runtime(isolated_state):
    """The toggle has to take effect now, not at the next restart."""
    reg = await _registry_with_seeded_groq()
    await dss.sync_byok_runtime(reg, _watsonx_source(), "ibm-cloud-key")
    assert reg.get_config(dss.byok_provider_id("watsonx")) is not None

    await dss.sync_byok_runtime(reg, _watsonx_source(allow_routing=False), "key")
    assert reg.get_config(dss.byok_provider_id("watsonx")) is None


@pytest.mark.asyncio
async def test_deleting_a_source_drops_its_runtime(isolated_state):
    reg = await _registry_with_seeded_groq()
    rec = _watsonx_source()
    save_providers([rec])
    await dss.sync_byok_runtime(reg, rec, "ibm-cloud-key")

    save_providers([])  # the record is gone by the time unsync runs
    await dss.unsync_source(_App(reg), "watsonx")
    assert reg.get_config(dss.byok_provider_id("watsonx")) is None


# ── A source whose kind IS seeded re-keys that provider instead ──────


@pytest.mark.asyncio
async def test_a_seeded_kind_is_rekeyed_rather_than_duplicated(isolated_state):
    """Groq is in the seed catalog, so the saved key goes onto that provider.
    Registering a second Groq runtime would double every candidate list."""
    reg = await _registry_with_seeded_groq()
    rec = ProviderRecord(
        name="groq", kind="groq", default_model=GROQ_MODEL, allow_routing=True
    )
    save_providers([rec])

    await dss.sync_source(_App(reg), "groq", "gsk_from_ui")

    assert reg.get_config(dss.byok_provider_id("groq")) is None
    assert reg.get_adapter("groq-free").api_key == "gsk_from_ui"


@pytest.mark.asyncio
async def test_a_model_chosen_outside_the_seed_list_is_declared(isolated_state):
    """A model picked from the live catalog may not be in the seed's ids, and
    the name heuristic cannot place a vendor-namespaced id on Groq."""
    reg = await _registry_with_seeded_groq()
    rec = ProviderRecord(
        name="groq", kind="groq", default_model="qwen/qwen3.6-27b", allow_routing=True
    )
    save_providers([rec])

    await dss.sync_source(_App(reg), "groq", "gsk_from_ui")
    await reg.update_health("groq-free", HealthStatus.HEALTHY)

    assert "qwen/qwen3.6-27b" in reg.get_config("groq-free").models
    routes = ProviderRouter(reg).resolve("qwen/qwen3.6-27b")
    assert [r.provider_id for r in routes] == ["groq-free"]


@pytest.mark.asyncio
async def test_declaring_a_model_twice_is_a_no_op(isolated_state):
    reg = await _registry_with_seeded_groq()
    assert dss.declare_model(reg, "groq", GROQ_MODEL) is False
    assert reg.get_config("groq-free").models == [GROQ_MODEL]
    assert dss.declare_model(reg, "groq", "") is False


# ── The cloud manifest ───────────────────────────────────────────────


def test_a_routing_enabled_source_defaults_to_cloud_visible(isolated_state):
    save_providers([_watsonx_source()])
    rec = ma.get("watsonx", WATSONX_MODEL)
    assert rec.visible_cloud is True
    assert rec.allow_routing is True


def test_a_routing_off_source_stays_cloud_private(isolated_state):
    save_providers([_watsonx_source(allow_routing=False)])
    rec = ma.get("watsonx", WATSONX_MODEL)
    assert rec.visible_cloud is False
    assert rec.allow_routing is False


def test_local_runtimes_keep_their_own_cloud_default(isolated_state):
    """Unchanged: Ollama and HomePilot publish by default, everything else
    follows its source's opt-in."""
    assert ma.get("ollama", "llama3.2:3b").visible_cloud is True
    assert ma.get("homepilot", "persona:nova").visible_cloud is True
    assert ma.get("some-other-source", "x").visible_cloud is False


def test_an_explicit_decision_survives_a_routing_change(isolated_state):
    """The default only applies to a model nobody has decided about."""
    save_providers([_watsonx_source()])
    ma.set_access("watsonx", WATSONX_MODEL, visible_cloud=False)
    assert ma.get("watsonx", WATSONX_MODEL).visible_cloud is False

    # Toggling routing on the source must not silently re-publish it.
    save_providers([_watsonx_source(allow_routing=True)])
    assert ma.get("watsonx", WATSONX_MODEL).visible_cloud is False


def test_the_cloud_manifest_carries_both_local_and_external_models(isolated_state):
    save_providers([_watsonx_source()])
    inventory = [
        ("ollama", "Ollama on this PC", "llama3.2:3b"),
        ("watsonx", "IBM watsonx.ai", WATSONX_MODEL),
    ]
    manifest = ma.cloud_manifest(inventory)
    by_id = {m["model_id"]: m for m in manifest}
    assert set(by_id) == {"llama3.2:3b", WATSONX_MODEL}
    assert by_id[WATSONX_MODEL]["source_id"] == "watsonx"
    assert by_id[WATSONX_MODEL]["source_label"] == "IBM watsonx.ai"
    assert by_id[WATSONX_MODEL]["allow_routing"] is True


def test_a_routing_off_source_is_absent_from_the_manifest(isolated_state):
    save_providers([_watsonx_source(allow_routing=False)])
    manifest = ma.cloud_manifest(
        [
            ("ollama", "Ollama on this PC", "llama3.2:3b"),
            ("watsonx", "IBM watsonx.ai", WATSONX_MODEL),
        ]
    )
    assert [m["model_id"] for m in manifest] == ["llama3.2:3b"]


# ── The inventory that feeds the manifest ────────────────────────────


def test_the_inventory_includes_every_connected_external_source(isolated_state):
    from ollabridge.api.model_access_routes import _external_source_models

    save_providers(
        [
            _watsonx_source(),
            ProviderRecord(
                name="groq",
                kind="groq",
                display_name="Groq",
                default_model=GROQ_MODEL,
                allow_routing=True,
            ),
        ]
    )
    inv = _external_source_models()
    assert (("watsonx", "IBM watsonx.ai", WATSONX_MODEL)) in inv
    assert (("groq", "Groq", GROQ_MODEL)) in inv


def test_the_inventory_skips_a_source_with_no_model_selected(isolated_state):
    from ollabridge.api.model_access_routes import _external_source_models

    save_providers([_watsonx_source(default_model="")])
    assert _external_source_models() == []


def test_the_inventory_skips_a_disabled_source(isolated_state):
    from ollabridge.api.model_access_routes import _external_source_models

    save_providers([_watsonx_source(enabled=False)])
    assert _external_source_models() == []


@pytest.mark.asyncio
async def test_a_byok_runtime_is_listed_by_the_local_models_endpoint(isolated_state):
    """A model offered to paired devices must also be visible to a client
    asking this machine what it can run — this is what /v1/models appends."""
    reg = await _registry_with_seeded_groq()
    await dss.sync_byok_runtime(reg, _watsonx_source(), "ibm-cloud-key")

    entries = dss.byok_runtime_models(reg)
    assert [e["id"] for e in entries] == [WATSONX_MODEL]
    assert entries[0]["object"] == "model"
    # The seeded Groq provider is not a BYOK runtime, so it is not duplicated
    # here — /v1/models already lists what it serves by other means.
    assert GROQ_MODEL not in [e["id"] for e in entries]


@pytest.mark.asyncio
async def test_the_models_listing_does_not_repeat_a_local_model(isolated_state):
    reg = await _registry_with_seeded_groq()
    await dss.sync_byok_runtime(reg, _watsonx_source(), "ibm-cloud-key")
    already = [{"id": WATSONX_MODEL, "object": "model"}]
    assert dss.byok_runtime_models(reg, already) == []


def test_the_inventory_also_carries_models_the_user_decided_about(isolated_state):
    """Picking a second model in Models & Access keeps it in the inventory,
    so a decision made there is not lost on the next manifest build."""
    from ollabridge.api.model_access_routes import _external_source_models

    save_providers([_watsonx_source()])
    ma.set_access("watsonx", "mistralai/mistral-large", visible_cloud=True)

    ids = [mid for _s, _l, mid in _external_source_models()]
    assert set(ids) == {WATSONX_MODEL, "mistralai/mistral-large"}
