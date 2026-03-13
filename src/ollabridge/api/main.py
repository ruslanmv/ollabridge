from __future__ import annotations

import logging
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


def _estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


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

    if settings.RELAY_ENABLED:
        app.include_router(build_relay_router(registry=app.state.relay_hub.registry, hub=app.state.relay_hub))

    from ollabridge.api.pair import router as pair_router

    app.include_router(pair_router)

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
                }
                if req.temperature is not None:
                    hp_payload["temperature"] = req.temperature
                if req.max_tokens is not None:
                    hp_payload["max_tokens"] = req.max_tokens

                data = await hp_connector.chat(base=node.endpoint or "", payload=hp_payload)
                content = data.get("content", "")

            else:
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

            return {
                "id": "ollabridge-chat",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                    }
                ],
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