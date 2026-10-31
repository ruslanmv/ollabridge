"""Short, stable component names for log lines.

Full logger names such as ``ollabridge.addons.providers.services.provider_loader``
push the message past column 80 and change whenever a module moves. Console
lines show a short component instead (``providers``); JSON output carries both
the component and the full logger name.

Matching is by dotted prefix and the longest prefix wins, so
``ollabridge.addons.providers.router`` is ``router`` while every other module
under ``ollabridge.addons.providers`` is ``providers``.
"""

from __future__ import annotations

from functools import lru_cache

#: Console column width for the component. Longer names are truncated.
WIDTH = 10

#: Names matched exactly, never as a parent: the package logger itself is the
#: gateway, but an unmapped ``ollabridge.utils.tunnel`` should read ``tunnel``.
_EXACT: dict[str, str] = {
    "ollabridge": "gateway",
}

_PREFIXES: dict[str, str] = {
    # Gateway core
    "ollabridge.api": "gateway",
    "ollabridge.cli": "gateway",
    "ollabridge.core": "gateway",
    "ollabridge.api.requests": "http",
    "ollabridge.api.relay": "relay",
    "ollabridge.api.avatar_session": "avatar",
    "ollabridge.api.world_state": "avatar",
    # Provider routing
    "ollabridge.addons.providers": "providers",
    "ollabridge.providers_routes": "providers",
    "ollabridge.addons.providers.router": "router",
    "ollabridge.addons.providers.secret_store": "secrets",
    "ollabridge.addons.providers.hf_catalog": "hfcatalog",
    # Local runtimes and their model catalog
    "ollabridge.addons.local_catalog": "catalog",
    "ollabridge.local_catalog": "catalog",
    "ollabridge.reachability": "runtime",
    "ollabridge.core.reachability": "runtime",
    "ollabridge.providers.ollama_client": "runtime",
    "ollabridge.ollama_setup": "runtime",
    # Everything else the gateway talks to
    "ollabridge.cloud": "cloud",
    "ollabridge.node": "node",
    "ollabridge.mcp": "mcp",
    "ollabridge.mcp_server": "mcp",
    "ollabridge.sources": "sources",
    "ollabridge.model_access": "models",
    "ollabridge.pairing": "pairing",
    "ollabridge.core.pairing": "pairing",
    "ollabridge.consumers": "consumers",
    "ollabridge.core.consumer_registry": "consumers",
    "ollabridge.session_bridge": "session",
    "ollabridge.core.session_bridge": "session",
    "ollabridge.media_routes": "media",
    "ollabridge.media_proxy": "media",
    "ollabridge.connectors.media_proxy": "media",
    "ollabridge.trace_relay": "traces",
    "ollabridge.connectors.trace_relay": "traces",
    "ollabridge.tracing": "store",
    "ollabridge.db": "store",
    # The ASGI server
    "uvicorn": "server",
    "uvicorn.error": "server",
    "uvicorn.asgi": "server",
    "uvicorn.access": "http",
}

#: Every component name a rule like ``catalog=debug`` can refer to.
COMPONENTS: frozenset[str] = frozenset(_PREFIXES.values()) | frozenset(_EXACT.values())


@lru_cache(maxsize=1024)
def component_for(logger_name: str) -> str:
    """Return the short component for *logger_name*.

    Unknown OllaBridge loggers fall back to their last dotted segment; third
    party loggers to their package (``httpx``, ``sqlalchemy``, ``asyncio``).
    """
    name = logger_name or "root"
    exact = _EXACT.get(name)
    if exact is not None:
        return exact
    probe = name
    while True:
        hit = _PREFIXES.get(probe)
        if hit is not None:
            return hit
        if "." not in probe:
            break
        probe = probe.rsplit(".", 1)[0]
    if name.startswith("ollabridge."):
        return name.rsplit(".", 1)[-1][:WIDTH]
    return name.split(".", 1)[0][:WIDTH]
