"""Provider credential operations shared by the CLI and doctor.

All functions redact secrets in their return values and never log keys.
"""

from __future__ import annotations

import datetime as dt

import httpx

from ollabridge.core.redact import redact_text
from ollabridge.providers_meta import (
    PROVIDER_CATALOG,
    ProviderRecord,
    env_key_for,
    get_record,
    load_providers,
    secret_key_for,
    upsert_record,
)


def _store():
    from ollabridge.addons.providers.secret_store import SecretStore

    return SecretStore()


def get_secret(name: str, store=None) -> str | None:
    """Resolve a provider key: encrypted store first, env var fallback."""
    s = store if store is not None else _store()
    return s.get(secret_key_for(name)) or env_key_for(name)


def set_secret(name: str, value: str, store=None) -> None:
    s = store if store is not None else _store()
    s.set(secret_key_for(name), value)


def delete_secret(name: str, store=None) -> bool:
    s = store if store is not None else _store()
    return s.delete(secret_key_for(name))


def rotate_secret(name: str, new_value: str, store=None) -> ProviderRecord:
    """Replace the stored key and stamp the rotation time in providers.yaml."""
    set_secret(name, new_value, store=store)
    rec = get_record(name) or ProviderRecord(
        name=name, kind=name if name in PROVIDER_CATALOG else "custom"
    )
    rec.rotated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    upsert_record(rec)
    return rec


def test_provider(name: str, *, store=None, timeout: float = 10.0) -> tuple[bool, str]:
    """Lightweight credential/health check. Never sends prompt content.

    Uses the provider's model-listing endpoint, which validates both
    reachability and the API key without incurring token costs.
    """
    rec = get_record(name)
    kind = rec.kind if rec and rec.kind else name
    spec = PROVIDER_CATALOG.get(kind)
    if spec is None:
        return False, f"unknown provider kind {kind!r}"

    key = get_secret(name, store=store)
    if not key:
        return False, "no API key configured (provider key missing)"

    base = (rec.base_url if rec and rec.base_url else spec.base_url).rstrip("/")
    if not base:
        return False, "no base_url configured for this provider"

    if kind == "anthropic":
        url = f"{base}/models"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        url = f"{base}{spec.models_path}"
        headers = {"Authorization": f"Bearer {key}"}

    try:
        r = httpx.get(url, headers=headers, timeout=timeout)
    except httpx.TimeoutException:
        return False, f"timeout after {timeout}s reaching {base}"
    except httpx.HTTPError as exc:
        return False, redact_text(f"{type(exc).__name__}: {exc}")

    outcome: tuple[bool, str]
    if r.status_code == 200:
        outcome = True, f"key valid, {base} reachable"
    elif r.status_code in (401, 403):
        outcome = False, f"key rejected (HTTP {r.status_code})"
    elif r.status_code == 429:
        outcome = False, "rate limited / quota exhausted (HTTP 429)"
    elif r.status_code == 402:
        outcome = False, "quota or billing failure (HTTP 402)"
    else:
        outcome = False, redact_text(f"HTTP {r.status_code}: {r.text[:120]}")

    if rec:
        rec.last_test_ok = outcome[0]
        rec.last_test_at = dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        upsert_record(rec)
    return outcome


def export_redacted(store=None) -> dict:
    """Safe export of provider configuration — keys are redacted hints only."""
    from ollabridge.core.redact import redact_secret

    out = []
    for rec in load_providers():
        key = get_secret(rec.name, store=store)
        out.append(
            {
                **rec.model_dump(),
                "key": redact_secret(key) if key else "(not set)",
                "key_configured": bool(key),
            }
        )
    return {"providers": out, "note": "keys are redacted; full keys are never exported"}
