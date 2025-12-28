from __future__ import annotations

from sqlmodel import SQLModel, create_engine, Session
from ollabridge.core.settings import settings


def db_url() -> str:
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    return f"sqlite:///{settings.DATA_DIR / 'ollabridge.sqlite'}"


engine = create_engine(db_url(), echo=False)


def init_db():
    SQLModel.metadata.create_all(engine)


def session() -> Session:
    return Session(engine)
