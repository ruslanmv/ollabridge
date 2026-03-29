from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from pydantic import BaseModel

from ollabridge.core.settings import settings
from ollabridge.core.security import require_api_key, set_pairing_manager
from ollabridge.core.enrollment import create_join_token
from ollabridge.core import runtime_settings as rts
from ollabridge.db.database import init_db, session
from ollabridge.db.models import RequestLog
from ollabridge.api.state import build_state
from ollabridge.api.relay import RelayHub, build_relay_router
from ollabridge.core.registry import RuntimeNodeState


log = logging.getLogger("ollabridge")
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None


class EmbeddingsReq(BaseModel):
    model: str | None = None
    input: str


class SourceHealthReq(BaseModel):
    source: str
    base_url: str
    api_key: str | None = None


class FlowEvent(BaseModel):
    ts: float
    path: str
    model: str | None = None
    ok: bool = True
    latency_ms: int = 0
    prompt_tokens_est: int = 0
    completion_tokens_est: int = 0


class SettingsPatch(BaseModel):
    default_model: str | None = None
    default_embed_model: str | None = None
    ollama_base_url: str | None = None
    local_runtime_enabled: bool | None = None
    homepilot_enabled: bool | None = None
    homepilot_base_url: str | None = None
    homepilot_api_key: str | None = None
    homepilot_node_id: str | None = None
    homepilot_node_tags: str | None = None


ALLOWED_SETTINGS_KEYS = {
    "default_model",
    "default_embed_model",
    "ollama_base_url",
    "local_runtime_enabled",
    "homepilot_enabled",
    "homepilot_base_url",
    "homepilot_api_key",
    "homepilot_node_id",
    "homepilot_node_tags",
}


def _parse_origins(raw: str) -> list[str]:
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


def _get_memory_bridge(app: FastAPI) -> "MemoryBridge":
    """Lazily initialise the shared MemoryBridge instance."""
    bridge = getattr(app.state, "_memory_bridge", None)
    if bridge is None:
        from ollabridge.connectors.memory_bridge import MemoryBridge

        bridge = MemoryBridge()
        app.state._memory_bridge = bridge
    return bridge


def _resolve_device_id(app: FastAPI, auth_key: str) -> str | None:
    """Resolve the device_id from an authenticated pairing token.

    Returns None for static API keys or local-trust connections.
    """
    mgr = getattr(app.state, "pairing_manager", None)
    if mgr is None or not auth_key or auth_key == "__local_trust__":
        return None
    return mgr.get_device_for_token(auth_key)


def _estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


# ---------------------------------------------------------------------------
# Response normalization — strip delivery artifacts before returning to client
# ---------------------------------------------------------------------------

_SHOW_TAG_RE = re.compile(r"\[show:[^\]]+\]", re.IGNORECASE)


def _normalize_content(raw_content: str) -> str:
    """Clean assistant text of delivery artifacts that clients cannot render.

    Handles two known patterns from HomePilot:
    1. JSON-wrapped final text: {"type":"final","text":"..."}
    2. [show:Label] image tags (VR/desktop clients can't render these yet)
    """
    text = raw_content or ""

    # 1. Unwrap {"type":"final","text":"..."} wrapper
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "text" in parsed:
                text = parsed["text"]
        except Exception:
            pass

    # 2. Strip [show:Label] tags
    text = _SHOW_TAG_RE.sub("", text)

    # 3. Collapse excess whitespace left by stripping
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text


def _record_flow_event(
    app: FastAPI,
    *,
    path: str,
    model: str | None,
    ok: bool,
    latency_ms: int,
    prompt_tokens_est: int = 0,
    completion_tokens_est: int = 0,
) -> None:
    events = getattr(app.state, "flow_events", None)
    if events is None:
        events = deque(maxlen=512)
        app.state.flow_events = events

    events.append(
        FlowEvent(
            ts=time.time(),
            path=path,
            model=model,
            ok=ok,
            latency_ms=latency_ms,
            prompt_tokens_est=prompt_tokens_est,
            completion_tokens_est=completion_tokens_est,
        ).model_dump()
    )


def _compute_flow_metrics(app: FastAPI) -> dict[str, Any]:
    now = time.time()
    events = list(getattr(app.state, "flow_events", []))
    recent_8 = [e for e in events if now - float(e.get("ts", 0)) <= 8]
    recent_60 = [e for e in events if now - float(e.get("ts", 0)) <= 60]

    requests_8s = len(recent_8)
    requests_1m = len(recent_60)
    prompt_1m = int(sum(int(e.get("prompt_tokens_est", 0) or 0) for e in recent_60))
    completion_1m = int(sum(int(e.get("completion_tokens_est", 0) or 0) for e in recent_60))
    total_1m = prompt_1m + completion_1m
    avg_latency_1m = (
        int(sum(int(e.get("latency_ms", 0) or 0) for e in recent_60) / requests_1m)
        if requests_1m
        else 0
    )

    return {
        "active": requests_8s > 0,
        "requests_8s": requests_8s,
        "requests_1m": requests_1m,
        "avg_latency_ms_1m": avg_latency_1m,
        "est_prompt_tokens_1m": prompt_1m,
        "est_completion_tokens_1m": completion_1m,
        "est_total_tokens_1m": total_1m,
        "est_tokens_per_sec": round(total_1m / 60.0, 2),
    }


async def _reconfigure_nodes(application: FastAPI, cfg: dict[str, Any]) -> None:
    registry = application.state.obridge.registry

    if cfg.get("local_runtime_enabled", True):
        ollama_url = cfg.get("ollama_base_url", settings.OLLAMA_BASE_URL)
        await registry.upsert(
            RuntimeNodeState(
                node_id=settings.LOCAL_NODE_ID,
                connector="local_ollama",
                endpoint=ollama_url,
                tags=[t.strip() for t in settings.LOCAL_NODE_TAGS.split(",") if t.strip()],
                models=[],
                capacity=1,
                meta={"via": "local"},
            )
        )
    else:
        await registry.remove(settings.LOCAL_NODE_ID)

    hp_enabled = cfg.get("homepilot_enabled", False)
    hp_node_id = cfg.get("homepilot_node_id", settings.HOMEPILOT_NODE_ID)

    if hp_enabled:
        hp_base = cfg.get("homepilot_base_url", settings.HOMEPILOT_BASE_URL)
        hp_key = cfg.get("homepilot_api_key", settings.HOMEPILOT_API_KEY)
        hp_tags_raw = cfg.get("homepilot_node_tags", settings.HOMEPILOT_NODE_TAGS)
        hp_tags = [t.strip() for t in hp_tags_raw.split(",") if t.strip()]

        from ollabridge.connectors.homepilot import HomePilotConnector

        hp_connector = getattr(application.state, "homepilot_connector", None)
        if hp_connector is None:
            hp_connector = HomePilotConnector()
            application.state.homepilot_connector = hp_connector

        hp_models: list[str] = []
        try:
            hp_models = await hp_connector.list_persona_models(base=hp_base, api_key=hp_key)
            log.info("HomePilot re-registered with %d models: %s", len(hp_models), hp_models[:5])
        except Exception as e:
            log.warning("HomePilot model discovery failed: %s", e)

        await registry.upsert(
            RuntimeNodeState(
                node_id=hp_node_id,
                connector="homepilot",
                endpoint=hp_base,
                tags=hp_tags,
                models=hp_models,
                capacity=2,
                meta={"via": "homepilot", "api_key": hp_key},
            )
        )
    else:
        await registry.remove(hp_node_id)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME)
    app.state.limiter = limiter
    app.state.obridge = build_state()
    app.state.relay_hub = RelayHub(app.state.obridge.registry)

    origins = _parse_origins(settings.CORS_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        init_db()
        app.state.flow_events = deque(maxlen=512)

        import asyncio

        cfg = rts.get_all()

        async def _init_nodes() -> None:
            await _reconfigure_nodes(app, cfg)

        asyncio.get_event_loop().create_task(_init_nodes())

        # Initialize addons: provider orchestration layer
        async def _init_providers() -> None:
            try:
                from ollabridge.addons.providers.services.provider_seeder import seed_providers
                registry, provider_router = await seed_providers()
                app.state.provider_registry = registry
                app.state.provider_router = provider_router
                log.info(
                    "Provider addon initialized: %d providers, %d aliases",
                    registry.provider_count, len(registry.aliases),
                )
            except Exception as exc:
                log.warning("Provider addon init failed (non-fatal): %s", exc)
                app.state.provider_registry = None
                app.state.provider_router = None

        asyncio.get_event_loop().create_task(_init_providers())

        # Initialize cloud bridge manager and auto-connect if credentials exist
        from ollabridge.cloud.bridge_manager import CloudBridgeManager
        bridge_mgr = CloudBridgeManager(
            ollama_base_url=settings.OLLAMA_BASE_URL,
            homepilot_base_url=settings.HOMEPILOT_BASE_URL,
            homepilot_api_key=settings.HOMEPILOT_API_KEY,
            homepilot_enabled=settings.HOMEPILOT_ENABLED,
        )
        app.state.cloud_bridge = bridge_mgr
        asyncio.get_event_loop().create_task(bridge_mgr.try_auto_connect())

    if settings.RELAY_ENABLED:
        app.include_router(build_relay_router(registry=app.state.relay_hub.registry, hub=app.state.relay_hub))

    from ollabridge.api.pair import router as pair_router
    from ollabridge.api.consumer_nodes import router as consumer_nodes_router
    from ollabridge.connectors.media_proxy import router as media_proxy_router

    app.include_router(pair_router)
    app.include_router(consumer_nodes_router)
    app.include_router(media_proxy_router)

    # World-State & Motion relay routes (additive — VR spatial awareness)
    from ollabridge.api.world_state import router as world_state_router
    app.include_router(world_state_router)

    # Trace relay routes (additive — embodiment trace → spatial memory)
    from ollabridge.api.trace_relay_routes import router as trace_relay_router
    app.include_router(trace_relay_router)

    # Cloud relay bridge (connect local GPU to OllaBridge Cloud)
    from ollabridge.api.cloud_routes import router as cloud_router
    app.include_router(cloud_router)

    if (settings.AUTH_MODE or "").lower().strip() == "pairing":
        import os
        from ollabridge.core.pairing import PairingManager, PairingCode

        mgr = PairingManager()
        initial_code = os.environ.pop("_OLLABRIDGE_INITIAL_PAIRING_CODE", "")
        if initial_code:
            import time as _time

            mgr._current_code = PairingCode(
                code=initial_code,
                created_at=_time.time(),
                ttl=settings.PAIRING_CODE_TTL_SECONDS,
            )
            log.info("Injected CLI pairing code into app PairingManager")

        app.state.pairing_manager = mgr
        set_pairing_manager(mgr)
        log.info("Pairing auth mode enabled — use /pair endpoints to pair devices")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        ok = True
        detail = "ok"
        try:
            nodes = await app.state.obridge.registry.list()
            ok = bool(nodes)
            detail = f"runtimes={len(nodes)}"
        except Exception as e:
            ok = False
            detail = str(e)

        cfg = rts.get_all()
        return {
            "status": "ok" if ok else "degraded",
            "mode": settings.MODE,
            "default_model": cfg.get("default_model", settings.DEFAULT_MODEL),
            "auth_mode": settings.AUTH_MODE,
            "detail": detail,
            "homepilot_enabled": cfg.get("homepilot_enabled", False),
            "local_runtime_enabled": cfg.get("local_runtime_enabled", True),
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        req: ChatReq,
        request: Request,
        _key: str = Depends(require_api_key),
    ) -> dict[str, Any]:
        model = req.model or rts.get("default_model", settings.DEFAULT_MODEL)
        t0 = time.time()
        prompt_tokens_est = sum(_estimate_tokens(m.content) for m in req.messages)

        try:
            payload_messages = [{"role": m.role, "content": m.content} for m in req.messages]
            decision = await app.state.obridge.router.choose_node(model=model)
            node = decision.node

            if node.connector == "relay_link":
                frame = await app.state.relay_hub.request(
                    node.node_id,
                    "chat",
                    {"model": model, "messages": payload_messages},
                )
                if not frame.get("ok", True):
                    raise RuntimeError(frame.get("error") or "upstream error")
                content = (frame.get("data") or {}).get("content", "")

            elif node.connector == "direct_endpoint":
                data = await app.state.obridge.direct.chat(
                    base=node.endpoint or "",
                    payload={"model": model, "messages": payload_messages},
                )
                content = data.get("content", "")

            elif node.connector == "homepilot":
                hp_connector = getattr(app.state, "homepilot_connector", None)
                if hp_connector is None:
                    from ollabridge.connectors.homepilot import HomePilotConnector

                    hp_connector = HomePilotConnector()
                    app.state.homepilot_connector = hp_connector

                hp_payload = {
                    "model": model,
                    "messages": payload_messages,
                    "api_key": (node.meta or {}).get("api_key", ""),
                    "client_type": request.headers.get("x-client-type", ""),
                }
                if req.temperature is not None:
                    hp_payload["temperature"] = req.temperature
                if req.max_tokens is not None:
                    hp_payload["max_tokens"] = req.max_tokens

                # --- Phase 2: Bridge session persistence ---
                # Resolve device identity and reuse existing HomePilot
                # conversation so Memory V2 continues naturally.
                device_id = _resolve_device_id(app, _key)
                bridge_session = None
                if device_id:
                    sessions = app.state.obridge.sessions
                    bridge_session = sessions.get_session(device_id, model)
                    if bridge_session:
                        hp_payload["conversation_id"] = bridge_session.homepilot_conversation_id
                        sessions.touch_session(device_id, model)

                data = await hp_connector.chat(base=node.endpoint or "", payload=hp_payload)

                # Forward structured errors from HomePilot (e.g. persona unpublished)
                if data.get("error"):
                    raise HTTPException(
                        status_code=data.get("status_code", 502),
                        detail=data.get("error_body", {"detail": "upstream error"}),
                    )

                content = data.get("content", "")

                # Store session mapping if we got a conversation_id back
                if device_id and not bridge_session:
                    conv_id = (data.get("raw") or {}).get("conversation_id", "")
                    if not conv_id:
                        # Use a stable hash so the same device+model always
                        # maps to the same conversation lineage
                        conv_id = f"hp-{device_id}-{model}"
                    app.state.obridge.sessions.upsert_session(
                        device_id=device_id,
                        model=model,
                        homepilot_conversation_id=conv_id,
                    )

            else:
                # --- Addon: multi-provider routing ---
                # Only route through the addon layer for recognized aliases
                # (free-best, free-fast, etc.).  Concrete model names must
                # fall through to the local Ollama instance below.
                provider_router = getattr(app.state, "provider_router", None)
                addon_handled = False
                if provider_router and provider_router.registry.is_alias(model):
                    try:
                        result_data = await provider_router.route_chat(
                            model, payload_messages,
                            temperature=req.temperature,
                            max_tokens=req.max_tokens,
                        )
                        choices = result_data.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "")
                            addon_handled = True
                    except Exception as addon_exc:
                        log.debug("Addon providers exhausted for alias=%s, falling back to Ollama: %s", model, addon_exc)

                if not addon_handled:
                    from ollabridge.providers.ollama_client import chat as ollama_chat
                    content = await ollama_chat(model=model, messages=payload_messages)

            latency = int((time.time() - t0) * 1000)

            with session() as s:
                s.add(
                    RequestLog(
                        path=str(request.url.path),
                        model=model,
                        latency_ms=latency,
                        ok=True,
                        client=request.client.host if request.client else None,
                    )
                )
                s.commit()

            _record_flow_event(
                app,
                path=str(request.url.path),
                model=model,
                ok=True,
                latency_ms=latency,
                prompt_tokens_est=prompt_tokens_est,
                completion_tokens_est=_estimate_tokens(content),
            )

            # --- Phase 1A: Normalize response text ---
            # Strip delivery artifacts (JSON wrappers, [show:] tags) that
            # non-web clients cannot render.
            client_type = request.headers.get("x-client-type", "")
            content = _normalize_content(content)

            result: dict[str, Any] = {
                "id": "ollabridge-chat",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            }

            # Attach persona context when client opts in via header
            include_ctx = (
                request.headers.get("x-include-persona-context", "").lower()
                in ("true", "1", "yes")
            )
            if include_ctx and node.connector == "homepilot":
                bridge = _get_memory_bridge(app)
                ctx = await bridge.fetch_context(
                    base=node.endpoint or "",
                    model=model,
                    api_key=(node.meta or {}).get("api_key", ""),
                )
                result["x_persona_context"] = ctx.to_dict()

            # --- Phase 4: Rewrite HomePilot attachment URLs to proxy URLs ---
            # If the upstream HomePilot response included x_attachments,
            # forward them through the OllaBridge media proxy.
            raw_data = data if node.connector == "homepilot" else {}
            upstream_attachments = (raw_data.get("raw") or {}).get("x_attachments", [])
            if upstream_attachments:
                from ollabridge.connectors.media_proxy import rewrite_attachment_urls
                result["x_attachments"] = rewrite_attachment_urls(upstream_attachments)

            # Forward x_directives if present
            upstream_directives = (raw_data.get("raw") or {}).get("x_directives")
            if upstream_directives:
                result["x_avatar_directives"] = upstream_directives

            return result

        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            with session() as s:
                s.add(
                    RequestLog(
                        path=str(request.url.path),
                        model=model,
                        latency_ms=latency,
                        ok=False,
                        client=request.client.host if request.client else None,
                    )
                )
                s.commit()

            _record_flow_event(
                app,
                path=str(request.url.path),
                model=model,
                ok=False,
                latency_ms=latency,
                prompt_tokens_est=prompt_tokens_est,
                completion_tokens_est=0,
            )
            raise HTTPException(500, str(e))

    # ------------------------------------------------------------------
    # Persona context endpoint — read-only bridge to HomePilot memory
    # ------------------------------------------------------------------

    @app.get("/v1/persona/context/{model:path}")
    async def persona_context(
        model: str,
        request: Request,
        _key: str = Depends(require_api_key),
    ) -> dict[str, Any]:
        """Return lightweight persona context for a HomePilot model.

        Clients (e.g. 3D-Avatar-Chatbot on Oculus Quest) call this once
        on model selection to get voice parameters, emotional baseline,
        user facts, and preferences — everything needed to personalise
        the avatar without re-fetching on every chat turn.
        """
        # Find the HomePilot node that serves this model
        try:
            decision = await app.state.obridge.router.choose_node(model=model)
            node = decision.node
        except Exception:
            return {"ok": False, "context": {}, "error": "no_node_for_model"}

        if node.connector != "homepilot":
            return {"ok": False, "context": {}, "error": "not_a_persona_model"}

        bridge = _get_memory_bridge(app)
        ctx = await bridge.fetch_context(
            base=node.endpoint or "",
            model=model,
            api_key=(node.meta or {}).get("api_key", ""),
        )

        return {"ok": True, "context": ctx.to_dict()}

    @app.post("/v1/embeddings")
    async def embeddings(
        req: EmbeddingsReq,
        request: Request,
        _key: str = Depends(require_api_key),
    ) -> dict[str, Any]:
        model = req.model or rts.get("default_embed_model", settings.DEFAULT_EMBED_MODEL)
        t0 = time.time()
        prompt_tokens_est = _estimate_tokens(req.input)

        try:
            decision = await app.state.obridge.router.choose_node(model=model)
            node = decision.node

            if node.connector == "relay_link":
                frame = await app.state.relay_hub.request(
                    node.node_id,
                    "embeddings",
                    {"model": model, "input": req.input},
                )
                if not frame.get("ok", True):
                    raise RuntimeError(frame.get("error") or "upstream error")
                vec = (frame.get("data") or {}).get("embedding", [])

            elif node.connector == "direct_endpoint":
                data = await app.state.obridge.direct.embeddings(
                    base=node.endpoint or "",
                    payload={"model": model, "input": req.input},
                )
                vec = data.get("embedding", [])

            else:
                from ollabridge.providers.ollama_client import embeddings as ollama_embed

                vec = await ollama_embed(model=model, text=req.input)

            latency = int((time.time() - t0) * 1000)
            with session() as s:
                s.add(
                    RequestLog(
                        path=str(request.url.path),
                        model=model,
                        latency_ms=latency,
                        ok=True,
                        client=request.client.host if request.client else None,
                    )
                )
                s.commit()

            _record_flow_event(
                app,
                path=str(request.url.path),
                model=model,
                ok=True,
                latency_ms=latency,
                prompt_tokens_est=prompt_tokens_est,
                completion_tokens_est=0,
            )

            return {
                "object": "list",
                "data": [{"object": "embedding", "embedding": vec, "index": 0}],
                "model": model,
            }

        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            with session() as s:
                s.add(
                    RequestLog(
                        path=str(request.url.path),
                        model=model,
                        latency_ms=latency,
                        ok=False,
                        client=request.client.host if request.client else None,
                    )
                )
                s.commit()

            _record_flow_event(
                app,
                path=str(request.url.path),
                model=model,
                ok=False,
                latency_ms=latency,
                prompt_tokens_est=prompt_tokens_est,
                completion_tokens_est=0,
            )
            raise HTTPException(500, str(e))

    @app.get("/admin/recent")
    async def admin_recent(_key: str = Depends(require_api_key)) -> dict[str, Any]:
        from sqlmodel import select

        with session() as s:
            rows = s.exec(select(RequestLog).order_by(RequestLog.ts.desc()).limit(200)).all()
            return {"recent": [r.model_dump() for r in rows]}

    @app.get("/admin/runtimes")
    async def admin_runtimes(_key: str = Depends(require_api_key)) -> dict[str, Any]:
        nodes = await app.state.obridge.registry.list()
        return {"runtimes": [n.__dict__ for n in nodes]}

    @app.post("/admin/enroll")
    async def admin_enroll(_key: str = Depends(require_api_key)) -> dict[str, Any]:
        tok = create_join_token()
        return {"token": tok.token, "expires_at": tok.expires_at.isoformat()}

    @app.get("/admin/connection-info")
    async def admin_connection_info(
        request: Request,
        _key: str = Depends(require_api_key),
    ) -> dict[str, Any]:
        cfg = rts.get_all()
        host = request.headers.get("host", f"localhost:{settings.PORT}")
        scheme = request.headers.get("x-forwarded-proto", "http")
        base_url = f"{scheme}://{host}/v1"

        keys = [k.strip() for k in settings.API_KEYS.split(",") if k.strip()]
        api_key = keys[0] if keys else ""
        api_key_masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else api_key

        model_names: list[str] = []
        try:
            nodes = await app.state.obridge.registry.list()
            for node in nodes:
                if not node.healthy:
                    continue
                if node.connector == "homepilot":
                    hp_connector = getattr(app.state, "homepilot_connector", None)
                    if hp_connector:
                        hp_key = ""
                        if isinstance(node.meta, dict):
                            hp_key = str(node.meta.get("api_key") or "")
                        data = await hp_connector.models(base=node.endpoint or "", api_key=hp_key)
                        model_names.extend(m.get("id", "") for m in data.get("data", []))
                elif node.connector == "local_ollama":
                    from ollabridge.providers.ollama_client import list_models as ollama_list

                    model_names.extend(await ollama_list())
        except Exception:
            pass

        return {
            "base_url": base_url,
            "api_key": api_key,
            "api_key_masked": api_key_masked,
            "default_model": cfg.get("default_model", settings.DEFAULT_MODEL),
            "auth_mode": settings.AUTH_MODE,
            "models": model_names[:20],
        }

    @app.get("/admin/settings")
    async def admin_get_settings(_key: str = Depends(require_api_key)) -> dict[str, Any]:
        cfg = rts.get_all()
        if cfg.get("homepilot_api_key"):
            cfg["homepilot_api_key_set"] = True
            cfg["homepilot_api_key"] = "***"
        else:
            cfg["homepilot_api_key_set"] = False
        return cfg

    @app.put("/admin/settings")
    async def admin_put_settings(request: Request, _key: str = Depends(require_api_key)) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Expected JSON body")

        if isinstance(payload, dict) and isinstance(payload.get("patch"), dict):
            payload = payload["patch"]

        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="Settings patch must be a JSON object")

        updates = {k: v for k, v in payload.items() if k in ALLOWED_SETTINGS_KEYS}
        if not updates:
            raise HTTPException(status_code=422, detail="No valid settings fields provided")

        if "homepilot_api_key" in payload:
            updates["homepilot_api_key"] = payload.get("homepilot_api_key", "")

        try:
            SettingsPatch(**updates)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))

        new_cfg = rts.update(updates)
        await _reconfigure_nodes(app, new_cfg)
        return {"ok": True, "settings": new_cfg}

    @app.post("/admin/source-health")
    async def admin_source_health(
        probe: SourceHealthReq,
        _key: str = Depends(require_api_key),
    ) -> dict[str, Any]:
        source = (probe.source or "").strip().lower()
        base = (probe.base_url or "").strip()

        if source not in {"ollama", "homepilot"}:
            raise HTTPException(status_code=422, detail="Unsupported source")
        if not base:
            raise HTTPException(status_code=422, detail="base_url is required")

        async with httpx.AsyncClient(timeout=12) as client:
            try:
                if source == "ollama":
                    url = f"{base.rstrip('/')}/api/tags"
                    r = await client.get(url)
                    r.raise_for_status()
                    data = r.json()
                    models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
                    return {
                        "ok": True,
                        "source": source,
                        "reachable": True,
                        "status_code": r.status_code,
                        "message": f"Connected — {len(models)} model(s) discovered",
                        "models": models[:20],
                    }

                headers = {}
                if probe.api_key:
                    headers["Authorization"] = f"Bearer {probe.api_key}"
                    headers["X-API-Key"] = probe.api_key

                url = f"{base.rstrip('/')}/v1/models"
                r = await client.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
                models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
                return {
                    "ok": True,
                    "source": source,
                    "reachable": True,
                    "status_code": r.status_code,
                    "message": f"Connected — {len(models)} persona model(s) discovered",
                    "models": models[:20],
                }

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status in {401, 403}:
                    message = "Authentication failed — check your API key"
                elif status == 404:
                    message = "Endpoint not found — verify the base URL"
                else:
                    message = f"HTTP {status} from source"

                return {
                    "ok": False,
                    "source": source,
                    "reachable": False,
                    "status_code": status,
                    "message": message,
                    "models": [],
                }

            except httpx.ConnectError:
                return {
                    "ok": False,
                    "source": source,
                    "reachable": False,
                    "message": "Connection refused — is the service running?",
                    "models": [],
                }

            except httpx.TimeoutException:
                return {
                    "ok": False,
                    "source": source,
                    "reachable": False,
                    "message": "Timed out while reaching the source",
                    "models": [],
                }

            except Exception as e:
                return {
                    "ok": False,
                    "source": source,
                    "reachable": False,
                    "message": f"Unexpected error: {e}",
                    "models": [],
                }

    @app.get("/admin/flow-metrics")
    async def admin_flow_metrics(_key: str = Depends(require_api_key)) -> dict[str, Any]:
        return _compute_flow_metrics(app)

    @app.get("/v1/models")
    async def list_models(response: Response, _key: str = Depends(require_api_key)) -> dict[str, Any]:
        all_models: list[dict[str, Any]] = []
        nodes = await app.state.obridge.registry.list()

        for node in nodes:
            if not node.healthy:
                continue
            try:
                if node.connector == "homepilot":
                    hp_connector = getattr(app.state, "homepilot_connector", None)
                    if hp_connector:
                        hp_key = ""
                        if isinstance(node.meta, dict):
                            hp_key = str(node.meta.get("api_key") or "")
                        data = await hp_connector.models(base=node.endpoint or "", api_key=hp_key)
                        for m in data.get("data", []):
                            if isinstance(m, dict):
                                m["owned_by"] = m.get("owned_by", "homepilot")
                                all_models.append(m)

                elif node.connector == "relay_link":
                    frame = await app.state.relay_hub.request(node.node_id, "models", {})
                    for m in (frame.get("data") or {}).get("data", []):
                        all_models.append(m)

                elif node.connector == "direct_endpoint":
                    data = await app.state.obridge.direct.models(base=node.endpoint or "")
                    for m in data.get("data", []):
                        all_models.append(m)

                else:
                    from ollabridge.providers.ollama_client import list_models as ollama_list

                    models = await ollama_list()
                    for m_name in models:
                        all_models.append({"id": m_name, "object": "model"})

            except Exception as e:
                log.warning("Failed to list models from node %s: %s", node.node_id, e)

        if not all_models:
            response.headers["X-OllaBridge-Warning"] = "models_unavailable"

        return {"object": "list", "data": all_models}

    ui_dir = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
    if ui_dir.is_dir():
        from fastapi.responses import FileResponse

        @app.get("/ui/{full_path:path}")
        async def ui_spa(full_path: str):
            file = ui_dir / full_path
            if file.is_file():
                return FileResponse(file)
            return FileResponse(ui_dir / "index.html")

    return app


app = create_app()