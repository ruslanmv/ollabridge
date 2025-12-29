from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ollabridge.core.settings import settings


@dataclass(frozen=True)
class JoinToken:
    """Short-lived token used by a Node to enroll into the Control Plane."""

    token: str
    expires_at: datetime


def _serializer() -> URLSafeTimedSerializer:
    # Stable salt so tokens remain verifiable across restarts.
    return URLSafeTimedSerializer(secret_key=settings.ENROLLMENT_SECRET, salt="obridge.enroll.v1")


def create_join_token(*, ttl_seconds: int | None = None) -> JoinToken:
    """Create a short-lived enrollment token.

    Tokens are *bearer* credentials; protect them like passwords.
    """

    ttl = ttl_seconds or settings.ENROLLMENT_TTL_SECONDS
    now = datetime.now(timezone.utc)
    payload = {
        "nonce": secrets.token_urlsafe(16),
        "iat": int(now.timestamp()),
    }
    token = _serializer().dumps(payload)
    return JoinToken(token=token, expires_at=now + timedelta(seconds=ttl))


def verify_join_token(token: str) -> dict:
    """Verify a join token; raises ValueError on failure."""

    try:
        data = _serializer().loads(token, max_age=settings.ENROLLMENT_TTL_SECONDS)
        if not isinstance(data, dict) or "nonce" not in data:
            raise ValueError("invalid token payload")
        return data
    except SignatureExpired as e:
        raise ValueError("token expired") from e
    except BadSignature as e:
        raise ValueError("invalid token") from e
