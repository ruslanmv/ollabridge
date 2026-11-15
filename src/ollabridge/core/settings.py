from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import model_validator
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

    # Data directory for every store: runtime settings, the request database,
    # pairing tokens, sessions, consumer nodes, catalogs, secrets, traces.
    # OLLABRIDGE_HOME wins over DATA_DIR (see _resolve_data_dir), matching
    # ollabridge.core.paths.data_dir(), so one variable relocates all state.
    DATA_DIR: Path = Path.home() / ".ollabridge"
    DATABASE_URL: str | None = None

    # Usage intelligence (docs/USAGE_INTELLIGENCE.md). Like traces, usage is
    # recorded locally as metadata only (never prompt or response text) in
    # <DATA_DIR>/usage.db. Nothing is uploaded unless the user turns on the
    # `usage_metadata` sync category.
    USAGE_ENABLED: bool = True
    # Price catalog YAML; empty = the bundled seed, which ships with no prices.
    USAGE_PRICING_FILE: str = ""
    # How Claude Code usage received over OTLP is billed: "subscription"
    # (Pro/Max plan — shown as an API-equivalent figure, never as spend) or
    # "api" (an API key — counted as spend).
    CLAUDE_CODE_BILLING: Literal["subscription", "api"] = "subscription"
    # Currency that costs are *shown* in. The ledger itself is always USD
    # (what providers charge); amounts are converted for display at this rate
    # = units of the currency per 1 USD, e.g. EUR with your own EUR-per-USD
    # rate. Can also be set from the dashboard or `ollabridge usage currency`.
    USAGE_DISPLAY_CURRENCY: str = "USD"
    USAGE_DISPLAY_RATE: float = 1.0
    # Seconds between usage uploads when usage_metadata sync is on.
    USAGE_SYNC_INTERVAL_SECONDS: float = 60.0

    @model_validator(mode="after")
    def _resolve_data_dir(self) -> "Settings":
        # Read from the process environment only, like core/paths.py; an empty
        # value counts as unset.
        home = os.environ.get("OLLABRIDGE_HOME", "").strip()
        self.DATA_DIR = Path(home).expanduser() if home else Path(self.DATA_DIR).expanduser()
        return self


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
