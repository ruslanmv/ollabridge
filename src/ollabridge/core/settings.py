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
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://localhost:8080,http://127.0.0.1:8080"

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

    # HomePilot integration — optional persona backend
    # Set HOMEPILOT_ENABLED=true + HOMEPILOT_BASE_URL to register HomePilot
    # personas as available models routed through OllaBridge.
    HOMEPILOT_ENABLED: bool = False
    HOMEPILOT_BASE_URL: str = "http://localhost:8000"
    HOMEPILOT_API_KEY: str = ""
    HOMEPILOT_NODE_ID: str = "homepilot"
    HOMEPILOT_NODE_TAGS: str = "homepilot,persona"

    # Authentication mode: required | local-trust | pairing
    #   required   – static API keys (default, backwards-compatible)
    #   local-trust – skip auth for loopback clients (127.0.0.1 / ::1)
    #   pairing    – device pairing via short-lived code exchange
    AUTH_MODE: str = "required"

    # Pairing settings (only used when AUTH_MODE=pairing)
    PAIRING_CODE_LENGTH: int = 6
    PAIRING_CODE_TTL_SECONDS: int = 300
    PAIRING_TOKEN_PREFIX: str = "mtx_"

    # Database
    DATA_DIR: Path = Path.home() / ".ollabridge"
    DATABASE_URL: str | None = None


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
