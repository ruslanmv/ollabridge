from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.util import get_remote_address
from pydantic import BaseModel

from ollabridge.core.settings import settings
from ollabridge.core.security import require_api_key, set_pairing_manager
from ollabridge.core.enrollment import create_join_token
from ollabridge.core import runtime_settings as rts
from ollabridge.db.database import init_db, session
from ollabridge.db.models import RequestLog
from ollabridge.api.state import build_state, AppState
from ollabridge.api.relay import RelayHub, build_relay_router
from ollabridge.core.registry import RuntimeNodeState


log = logging.getLogger("ollabridge")
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT])


# ----------------------------
# Request/Response Models
# ----------------------------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float | None = None


class EmbeddingsReq(BaseModel):
    model: str | None = None
    input: str


def _parse_origins(raw: str) -> list[str]:
    """Parse CORS origins from comma-separated string with robust handling."""
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME)
    app.state.limiter = limiter
    app.state.obridge = build_state()
    app.state.relay_hub = RelayHub(app.state.obridge.registry)

    # CORS: only enable if origins are configured
    origins = _parse_origins(settings.CORS_ORIGINS)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],  # important so Authorization / X-API-Key works
        )

    @app.on_event("startup")
    def _startup():
        init_db()
        # Register nodes based on persisted runtime settings (or env defaults).
        # This means settings saved via the UI persist across restarts.
        import asyncio
        cfg = rts.get_all()

        async def _init_nodes():
            await _reconfigure_nodes(app, cfg)

        asyncio.get_event_loop().create_task(_init_nodes())

    # Relay (node enrollment link)
    if settings.RELAY_ENABLED:
        app.include_router(build_relay_router(registry=app.state.obridge.registry, hub=app.state.relay_hub))

    # Pair router: always mounted so UI can manage pairing.
    # When AUTH_MODE=pairing, also pre-create PairingManager at startup.
    from ollabridge.api.pair import router as pair_router
    app.include_router(pair_router)
    if (settings.AUTH_MODE or "").lower().strip() == "pairing":
        from ollabridge.core.pairing import PairingManager
        mgr = PairingManager()
        app.state.pairing_manager = mgr
        set_pairing_manager(mgr)
        log.info("Pairing auth mode enabled — use /pair endpoints to pair devices")

    # ----------------------------
    # Health
    # ----------------------------
    @app.get("/health")
    async def health():
        ok = True
        detail = "ok"
        # Best-effort: healthy if at least one runtime is registered.
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

    # ----------------------------
    # OpenAI-compatible
    # ----------------------------
    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatReq, request: Request, _key: str = Depends(require_api_key)) -> dict[str, Any]:
        model = (req.model or rts.get("default_model", settings.DEFAULT_MODEL))
        t0 = time.time()
        try:
            payload_messages = [{"role": m.role, "content": m.content} for m in req.messages]
            # Route to a node
            decision = await app.state.obridge.router.choose_node(model=model)
            node = decision.node
            if node.connector == "relay_link":
                frame = await app.state.relay_hub.request(node.node_id, "chat", {"model": model, "messages": payload_messages})
                if not frame.get("ok", True):
                    raise RuntimeError(frame.get("error") or "upstream error")
                content = (frame.get("data") or {}).get("content", "")
            elif node.connector == "direct_endpoint":
                data = await app.state.obridge.direct.chat(base=node.endpoint or "", payload={"model": model, "messages": payload_messages})
                content = data.get("content", "")
            elif node.connector == "homepilot":
                # Route to HomePilot persona backend
                hp_connector = getattr(app.state, "homepilot_connector", None)
                if hp_connector is None:
                    from ollabridge.connectors.homepilot import HomePilotConnector
                    hp_connector = HomePilotConnector()
                    app.state.homepilot_connector = hp_connector
                hp_payload = {
                    "model": model,
                    "messages": payload_messages,
                    "api_key": (node.meta or {}).get("api_key", ""),
                }
                if req.temperature is not None:
                    hp_payload["temperature"] = req.temperature
                data = await hp_connector.chat(base=node.endpoint or "", payload=hp_payload)
                content = data.get("content", "")
            else:
                # local_ollama fallback path
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

            return {
                "id": "ollabridge-chat",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
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
            raise HTTPException(500, str(e))

    @app.post("/v1/embeddings")
    async def embeddings(req: EmbeddingsReq, request: Request, _key: str = Depends(require_api_key)) -> dict[str, Any]:
        model = (req.model or rts.get("default_embed_model", settings.DEFAULT_EMBED_MODEL))
        t0 = time.time()
        try:
            decision = await app.state.obridge.router.choose_node(model=model)
            node = decision.node
            if node.connector == "relay_link":
                frame = await app.state.relay_hub.request(node.node_id, "embeddings", {"model": model, "input": req.input})
                if not frame.get("ok", True):
                    raise RuntimeError(frame.get("error") or "upstream error")
                vec = (frame.get("data") or {}).get("embedding", [])
            elif node.connector == "direct_endpoint":
                data = await app.state.obridge.direct.embeddings(base=node.endpoint or "", payload={"model": model, "input": req.input})
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

            return {"object": "list", "data": [{"object": "embedding", "embedding": vec, "index": 0}], "model": model}
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
            raise HTTPException(500, str(e))

    # ----------------------------
    # Admin
    # ----------------------------
    @app.get("/admin/recent")
    async def admin_recent(_key: str = Depends(require_api_key)):
        from sqlmodel import select

        with session() as s:
            rows = s.exec(select(RequestLog).order_by(RequestLog.ts.desc()).limit(200)).all()
            return {"recent": [r.model_dump() for r in rows]}

    @app.get("/admin/runtimes")
    async def admin_runtimes(_key: str = Depends(require_api_key)):
        nodes = await app.state.obridge.registry.list()
        return {"runtimes": [n.__dict__ for n in nodes]}

    @app.post("/admin/enroll")
    async def admin_enroll(_key: str = Depends(require_api_key)):
        tok = create_join_token()
        return {"token": tok.token, "expires_at": tok.expires_at.isoformat()}

    @app.get("/admin/connection-info")
    async def admin_connection_info(request: Request, _key: str = Depends(require_api_key)):
        """Return the client configuration needed to connect to this gateway."""
        cfg = rts.get_all()
        # Derive the external base URL from the request
        host = request.headers.get("host", f"localhost:{settings.PORT}")
        scheme = request.headers.get("x-forwarded-proto", "http")
        base_url = f"{scheme}://{host}/v1"

        # Get first API key for display (masked partially)
        keys = [k.strip() for k in settings.API_KEYS.split(",") if k.strip()]
        api_key = keys[0] if keys else ""
        api_key_masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else api_key

        # Get available models
        model_names: list[str] = []
        try:
            nodes = await app.state.obridge.registry.list()
            for node in nodes:
                if not node.healthy:
                    continue
                if node.connector == "homepilot":
                    hp_connector = getattr(app.state, "homepilot_connector", None)
                    if hp_connector:
                        data = await hp_connector.models(base=node.endpoint or "")
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

    # ----------------------------
    # Settings (runtime-configurable from UI)
    # ----------------------------
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

    @app.get("/admin/settings")
    async def admin_get_settings(_key: str = Depends(require_api_key)):
        cfg = rts.get_all()
        # Mask api key for safety
        if cfg.get("homepilot_api_key"):
            cfg["homepilot_api_key_set"] = True
            cfg["homepilot_api_key"] = "***"
        else:
            cfg["homepilot_api_key_set"] = False
        return cfg

    @app.put("/admin/settings")
    async def admin_put_settings(patch: SettingsPatch, _key: str = Depends(require_api_key)):
        # Only include fields that were explicitly sent
        updates = {k: v for k, v in patch.model_dump().items() if v is not None}
        # Special case: allow setting homepilot_api_key to empty string
        raw = await _get_body_json(patch)
        if "homepilot_api_key" in raw and raw["homepilot_api_key"] is not None:
            updates["homepilot_api_key"] = raw["homepilot_api_key"]
        new_cfg = rts.update(updates)
        # Re-register nodes based on new settings
        await _reconfigure_nodes(app, new_cfg)
        return {"ok": True, "settings": new_cfg}

    async def _get_body_json(patch: SettingsPatch) -> dict:
        """Return the raw dict from model — needed to detect explicit empty strings."""
        return patch.model_dump(exclude_unset=False)

    async def _reconfigure_nodes(application: FastAPI, cfg: dict) -> None:
        """Re-register / remove runtime nodes based on updated settings."""
        registry = application.state.obridge.registry

        # ── Local Ollama node ────────────────────────────────────────
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

        # ── HomePilot node ───────────────────────────────────────────
        hp_enabled = cfg.get("homepilot_enabled", False)
        hp_node_id = cfg.get("homepilot_node_id", settings.HOMEPILOT_NODE_ID)

        if hp_enabled:
            hp_base = cfg.get("homepilot_base_url", settings.HOMEPILOT_BASE_URL)
            hp_key = cfg.get("homepilot_api_key", settings.HOMEPILOT_API_KEY)
            hp_tags_raw = cfg.get("homepilot_node_tags", settings.HOMEPILOT_NODE_TAGS)
            hp_tags = [t.strip() for t in hp_tags_raw.split(",") if t.strip()]

            # Ensure HomePilot connector exists
            from ollabridge.connectors.homepilot import HomePilotConnector
            hp_connector = getattr(application.state, "homepilot_connector", None)
            if hp_connector is None:
                hp_connector = HomePilotConnector()
                application.state.homepilot_connector = hp_connector

            # Discover models
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

    @app.get("/v1/models")
    async def list_models(response: Response, _key: str = Depends(require_api_key)):
        all_models: list[dict[str, Any]] = []

        # Aggregate models from all healthy nodes
        nodes = await app.state.obridge.registry.list()
        for node in nodes:
            if not node.healthy:
                continue
            try:
                if node.connector == "homepilot":
                    # Fetch persona models from HomePilot
                    hp_connector = getattr(app.state, "homepilot_connector", None)
                    if hp_connector:
                        data = await hp_connector.models(base=node.endpoint or "")
                        for m in data.get("data", []):
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
                    # local_ollama
                    from ollabridge.providers.ollama_client import list_models as ollama_list
                    models = await ollama_list()
                    for m_name in models:
                        all_models.append({"id": m_name, "object": "model"})
            except Exception as e:
                log.warning("Failed to list models from node %s: %s", node.node_id, e)

        if not all_models:
            response.headers["X-OllaBridge-Warning"] = "models_unavailable"

        return {"object": "list", "data": all_models}

    # ----------------------------
    # Serve frontend SPA (if built)
    # ----------------------------
    ui_dir = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
    if ui_dir.is_dir():
        from fastapi.responses import FileResponse

        @app.get("/ui/{full_path:path}")
        async def ui_spa(full_path: str):
            """Serve the frontend SPA — fall back to index.html for client-side routing."""
            file = ui_dir / full_path
            if file.is_file():
                return FileResponse(file)
            return FileResponse(ui_dir / "index.html")

    return app


app = create_app()
