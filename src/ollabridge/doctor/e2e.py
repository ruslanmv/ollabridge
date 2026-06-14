"""End-to-end request path verification.

Two probes, both using a fixed non-sensitive test prompt:

* **local e2e** — client → local gateway → local model (always available).
* **cloud e2e** — client → OllaBridge Cloud → relay → this device → model
  → cloud → client. Requires cloud pairing, a running gateway with the
  relay connected, and a cloud API key (``OLLABRIDGE_CLOUD_API_KEY``).

Relay latency is estimated as (cloud round-trip − local round-trip) for the
same model and prompt.
"""

from __future__ import annotations

import time

import httpx

from ollabridge.cloud.device_config import load_cloud_device_credentials
from ollabridge.cloud.sync_config import load_sync_config
from ollabridge.core.settings import settings
from ollabridge.doctor.checks import (
    _cloud_api_key,
    _local_api_key,
    _local_models,
    LOGIN_HINT,
)
from ollabridge.doctor.models import CheckResult, SectionReport

TEST_PROMPT = "Reply with the single word: pong"


def _chat(
    base_url: str, api_key: str, model: str, timeout: float
) -> tuple[bool, int, dict]:
    """POST a minimal chat completion. Returns (ok, latency_ms, info)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "temperature": 0.0,
    }
    t0 = time.time()
    try:
        r = httpx.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
    except Exception as exc:
        return (
            False,
            int((time.time() - t0) * 1000),
            {"error": f"{type(exc).__name__}: {exc}"},
        )
    latency = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        return False, latency, {"error": f"HTTP {r.status_code}: {r.text[:160]}"}
    body = r.json()
    usage = body.get("usage") or {}
    return (
        True,
        latency,
        {
            "tokens_in": usage.get("prompt_tokens"),
            "tokens_out": usage.get("completion_tokens"),
        },
    )


def check_e2e(
    port: int | None = None, model: str = "", timeout: float = 120.0
) -> SectionReport:
    sec = SectionReport(name="End-to-end")
    port = port or settings.PORT
    local_key = _local_api_key()
    sync = load_sync_config()

    models = _local_models()
    target = model or (models[0] if models else "")
    if not target:
        sec.add(
            CheckResult.fail(
                "Test model available",
                "no local models detected",
                hint="Pull a model:  ollama pull llama3.1",
            )
        )
        return sec
    sec.add(CheckResult.ok("Test model available", target))

    if not local_key:
        sec.add(
            CheckResult.fail(
                "Local API key",
                "no API key available for the probe",
                hint="Set API_KEYS or note the key printed by `ollabridge start`",
            )
        )
        return sec

    ok, local_ms, info = _chat(f"http://localhost:{port}", local_key, target, timeout)
    if ok:
        detail = f"{local_ms} ms (client → local gateway → {target})"
        if info.get("tokens_in") is not None:
            detail += f", tokens in/out: {info['tokens_in']}/{info['tokens_out']}"
        sec.add(
            CheckResult.ok(
                "Local request path", detail, latency_ms=local_ms, route="local", **info
            )
        )
    else:
        sec.add(
            CheckResult.fail(
                "Local request path",
                str(info.get("error", "failed")),
                hint="Run:  ollabridge start",
            )
        )
        return sec

    creds = load_cloud_device_credentials()
    if not creds:
        sec.add(
            CheckResult.skip(
                "Cloud relay path", "not paired with OllaBridge Cloud", hint=LOGIN_HINT
            )
        )
        return sec
    cloud_key = _cloud_api_key()
    if not cloud_key:
        sec.add(
            CheckResult.skip(
                "Cloud relay path",
                "set OLLABRIDGE_CLOUD_API_KEY (a cloud API key) to test client → cloud → relay → device",
            )
        )
        return sec

    ok, cloud_ms, info = _chat(creds.cloud_url, cloud_key, target, timeout)
    if ok:
        relay_ms = max(0, cloud_ms - local_ms)
        detail = (
            f"total {cloud_ms} ms, est. relay overhead {relay_ms} ms, "
            f"model {local_ms} ms (route: client → cloud → relay → {creds.device_id} → {target})"
        )
        if info.get("tokens_in") is not None:
            detail += f", tokens in/out: {info['tokens_in']}/{info['tokens_out']}"
        sec.add(
            CheckResult.ok(
                "Cloud relay path",
                detail,
                total_latency_ms=cloud_ms,
                relay_latency_ms=relay_ms,
                model_latency_ms=local_ms,
                route="cloud-relay",
                **info,
            )
        )
    else:
        err = str(info.get("error", ""))
        hint = "Is the gateway running with the relay connected? Check:  ollabridge doctor relay"
        if "401" in err or "403" in err:
            hint = "Cloud API key rejected — mint a new key in the cloud dashboard"
        elif "404" in err or "model" in err.lower():
            hint = (
                "Model not registered with cloud — keep the gateway online and re-check"
            )
        sec.add(CheckResult.fail("Cloud relay path", err, hint=hint))

    sec.add(
        CheckResult.ok(
            "Prompt logging during test",
            "enabled" if sync.prompt_logging else "disabled (default)",
        )
    )
    sec.notes.append("Fallback was not exercised by this probe (single fixed route).")
    return sec
