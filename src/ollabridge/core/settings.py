from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment and optional .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    APP_NAME: str = "OllaBridge"
    ENV: str = "dev"
    HOST: str = "0.0.0.0"
    PORT: int = 11435
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Auth (comma-separated API keys)
    API_KEYS: str = "dev-key-change-me"

    # Rate limiting (slowapi syntax)
    RATE_LIMIT: str = "60/minute"

    # Upstream: Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_CHAT_PATH: str = "/api/chat"
    OLLAMA_EMBED_PATH: str = "/api/embeddings"
    DEFAULT_MODEL: str = "deepseek-r1"
    DEFAULT_EMBED_MODEL: str = "nomic-embed-text"

    # Control-plane / Node enrollment
    MODE: str = "gateway"  # gateway | node
    RELAY_ENABLED: bool = True
    ENROLLMENT_SECRET: str = "dev-enroll-change-me"
    ENROLLMENT_TTL_SECONDS: int = 3600

    # When running in gateway mode, register local runtime as a default node
    LOCAL_RUNTIME_ENABLED: bool = True
    LOCAL_NODE_ID: str = "local"
    LOCAL_NODE_TAGS: str = "local"

    # Database
    DATA_DIR: Path = Path.home() / ".ollabridge"
    DATABASE_URL: str | None = None


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
