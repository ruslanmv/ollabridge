from __future__ import annotations

from pydantic import BaseModel, Field


class OAChatMessage(BaseModel):
    role: str
    content: str


class OAChatRequest(BaseModel):
    model: str | None = None
    messages: list[OAChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool | None = False


class OAChatChoice(BaseModel):
    index: int = 0
    message: OAChatMessage
    finish_reason: str | None = "stop"


class OAChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    choices: list[OAChatChoice]


class OAEmbeddingsRequest(BaseModel):
    model: str | None = None
    input: str | list[str]


class OAEmbeddingData(BaseModel):
    index: int
    embedding: list[float]


class OAEmbeddingsResponse(BaseModel):
    object: str = "list"
    data: list[OAEmbeddingData]
    model: str | None = None
