from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from pydantic import BaseModel

from ollabridge.core.settings import settings
from ollabridge.core.security import require_api_key
from ollabridge.core.enrollment import create_join_token
from ollabridge.db.database import init_db, session
from ollabridge.db.models import RequestLog
from ollabridge.api.state import build_state, AppState
from ollabridge.api.relay import RelayHub, build_relay_router
from ollabridge.core.registry import RuntimeNodeState


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


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME)
    app.state.limiter = limiter
    app.state.obridge = build_state()
    app.state.relay_hub = RelayHub(app.state.obridge.registry)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup():
        init_db()
        # Optional: register a local runtime as a direct endpoint node.
        if settings.LOCAL_RUNTIME_ENABLED:
            # In v1 the gateway and runtime are colocated; node agent is optional.
            # We treat local Ollama as a direct node via built-in provider calls.
            # The Node Agent path is used for remote nodes.
            import asyncio
            async def _reg():
                await app.state.obridge.registry.upsert(
                    RuntimeNodeState(
                        node_id=settings.LOCAL_NODE_ID,
                        connector="local_ollama",
                        endpoint=settings.OLLAMA_BASE_URL,
                        tags=[t.strip() for t in settings.LOCAL_NODE_TAGS.split(",") if t.strip()],
                        models=[],
                        capacity=1,
                        meta={"via": "local"},
                    )
                )
            asyncio.get_event_loop().create_task(_reg())

    # Relay (node enrollment link)
    if settings.RELAY_ENABLED:
        app.include_router(build_relay_router(registry=app.state.obridge.registry, hub=app.state.relay_hub))

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

        return {
            "status": "ok" if ok else "degraded",
            "mode": settings.MODE,
            "default_model": settings.DEFAULT_MODEL,
            "detail": detail,
        }

    # ----------------------------
    # OpenAI-compatible
    # ----------------------------
    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatReq, request: Request, _key: str = Depends(require_api_key)) -> dict[str, Any]:
        model = (req.model or settings.DEFAULT_MODEL)
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
        model = (req.model or settings.DEFAULT_EMBED_MODEL)
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

    @app.get("/v1/models")
    async def list_models(_key: str = Depends(require_api_key)):
        # Aggregate best-effort from first healthy node.
        try:
            decision = await app.state.obridge.router.choose_node()
            node = decision.node
            if node.connector == "relay_link":
                frame = await app.state.relay_hub.request(node.node_id, "models", {})
                return frame.get("data") or {"data": []}
            if node.connector == "direct_endpoint":
                return await app.state.obridge.direct.models(base=node.endpoint or "")
            from ollabridge.providers.ollama_client import list_models as ollama_list

            models = await ollama_list()
            return {"object": "list", "data": [{"id": m, "object": "model"} for m in models]}
        except Exception:
            return {"object": "list", "data": []}

    return app


app = create_app()
