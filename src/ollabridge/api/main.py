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
from ollabridge.db.database import init_db, session
from ollabridge.db.models import RequestLog
from ollabridge.providers.ollama_client import chat as ollama_chat, embeddings as ollama_embed


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

    # ----------------------------
    # Health
    # ----------------------------
    @app.get("/health")
    async def health():
        ok = True
        detail = "ok"
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
                r.raise_for_status()
        except Exception as e:
            ok = False
            detail = str(e)

        return {
            "status": "ok" if ok else "degraded",
            "ollama_base_url": settings.OLLAMA_BASE_URL,
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
            vec = await ollama_embed(model=model, prompt=req.input)

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

    return app


app = create_app()
