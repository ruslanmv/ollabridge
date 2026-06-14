"""Doctor check implementations.

Each ``check_*`` function returns a :class:`SectionReport` and must never
raise: failures become FAIL/WARN results with remediation hints. No check
ever prints or stores a full credential, and none sends prompt content
except the explicit e2e probe (a fixed, non-sensitive test prompt).
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import time

import httpx

from ollabridge.cloud.device_config import load_cloud_device_credentials
from ollabridge.cloud.sync_config import load_sync_config
from ollabridge.core import paths
from ollabridge.core.redact import redact_secret
from ollabridge.core.settings import settings
from ollabridge.doctor.models import CheckResult, SectionReport

LOGIN_HINT = "Run:  ollabridge login"


def _local_api_key() -> str:
    """Best-effort local API key: env → .env → settings (placeholders ignored)."""
    candidates = [os.environ.get("API_KEYS", ""), settings.API_KEYS or ""]
    try:
        from ollabridge.cli.main import _read_api_keys_from_dotenv

        candidates.insert(1, _read_api_keys_from_dotenv() or "")
    except Exception:
        pass
    for raw in candidates:
        key = (raw or "").split(",")[0].strip()
        if key and "change-me" not in key and "dev-key" not in key:
            return key
    return ""


def _cloud_api_key() -> str:
    return os.environ.get("OLLABRIDGE_CLOUD_API_KEY", "").strip()


def _relay_ws_url(cloud_url: str) -> str:
    raw = cloud_url.rstrip("/")
    if raw.endswith("/relay/connect"):
        return raw
    for prefix in ("wss://", "ws://", "https://", "http://"):
        if raw.startswith(prefix):
            host = raw[len(prefix) :].split("/")[0]
            scheme = "wss" if prefix in ("wss://", "https://") else "ws"
            return f"{scheme}://{host}/relay/connect"
    return f"wss://{raw.split('/')[0]}/relay/connect"


# ── Local ───────────────────────────────────────────────────────────────


def check_local(
    port: int | None = None, ollama_base: str | None = None
) -> SectionReport:
    sec = SectionReport(name="Local")
    port = port or settings.PORT
    ollama_base = ollama_base or settings.OLLAMA_BASE_URL

    try:
        version = importlib.metadata.version("ollabridge")
        sec.add(CheckResult.ok("Python package installed", f"ollabridge {version}"))
    except importlib.metadata.PackageNotFoundError:
        sec.add(
            CheckResult.warn(
                "Python package installed", "running from source (not pip-installed)"
            )
        )

    try:
        d = paths.data_dir()
        sec.add(CheckResult.ok("Local config readable", str(d)))
    except Exception as exc:
        sec.add(CheckResult.fail("Local config readable", str(exc)))

    key = _local_api_key()
    if key:
        sec.add(CheckResult.ok("API key configured", redact_secret(key)))
    else:
        sec.add(
            CheckResult.warn(
                "API key configured",
                "no non-default API key found",
                hint="`ollabridge start` generates one, or set API_KEYS in .env",
            )
        )

    try:
        r = httpx.get(f"http://localhost:{port}/health", timeout=3)
        if r.status_code == 200:
            sec.add(
                CheckResult.ok(
                    "Local server reachable", f"http://localhost:{port}/health"
                )
            )
        else:
            sec.add(CheckResult.fail("Local server reachable", f"HTTP {r.status_code}"))
    except Exception as exc:
        sec.add(
            CheckResult.fail(
                "Local server reachable",
                f"{type(exc).__name__}: not running on port {port}?",
                hint="Run:  ollabridge start",
            )
        )

    try:
        r = httpx.get(f"{ollama_base}/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m.get("name", "") for m in r.json().get("models", [])]
            sec.add(CheckResult.ok("Ollama reachable", ollama_base))
            sec.add(
                CheckResult.ok(
                    "Models detected", f"{len(models)} local models", models=models
                )
            )
        else:
            sec.add(CheckResult.fail("Ollama reachable", f"HTTP {r.status_code}"))
    except Exception as exc:
        sec.add(
            CheckResult.warn(
                "Ollama reachable",
                f"{type(exc).__name__} at {ollama_base}",
                hint="Install/start Ollama, or configure another backend in the UI",
            )
        )
    return sec


# ── Cloud ───────────────────────────────────────────────────────────────


def check_cloud() -> SectionReport:
    sec = SectionReport(name="Cloud")
    creds = load_cloud_device_credentials()
    if not creds:
        sec.add(
            CheckResult.fail(
                "Cloud credentials found",
                "no credentials at " f"{paths.cloud_device_file()}",
                hint=LOGIN_HINT,
            )
        )
        sec.notes.append("Cloud is optional — local mode works without it.")
        return sec

    sec.add(CheckResult.ok("Cloud credentials found", f"device {creds.device_id}"))

    reachable = False
    for probe in ("/health", "/"):
        try:
            r = httpx.get(
                creds.cloud_url.rstrip("/") + probe, timeout=5, follow_redirects=True
            )
            if r.status_code < 500:
                reachable = True
                break
        except Exception:
            continue
    if reachable:
        sec.add(CheckResult.ok("Cloud API reachable", creds.cloud_url))
    else:
        sec.add(
            CheckResult.fail(
                "Cloud API reachable", creds.cloud_url, hint="Check network / cloud URL"
            )
        )

    sec.add(CheckResult.ok("Device paired", f"{creds.device_id} → {creds.cloud_url}"))

    sync = load_sync_config()
    if sync.enabled:
        sec.add(CheckResult.ok("Sync enabled", "metadata sync is on"))
    else:
        sec.add(
            CheckResult.warn(
                "Sync enabled",
                "cloud sync is disabled",
                hint="Run:  ollabridge sync enable",
            )
        )
    if sync.prompt_logging:
        sec.add(
            CheckResult.warn(
                "Prompt logging",
                "ENABLED — prompts may be stored",
                hint="Run:  ollabridge sync config prompt_logging false",
            )
        )
    else:
        sec.add(CheckResult.ok("Prompt logging", "disabled (default)"))
    risky = sync.sensitive_enabled()
    if risky and risky != ["prompt_logging"]:
        sec.notes.append(f"Sensitive sync opt-ins active: {', '.join(risky)}")
    return sec


# ── Relay ───────────────────────────────────────────────────────────────


async def _relay_probe(
    cloud_url: str, device_token: str, models: list[str], timeout: float = 10.0
) -> dict:
    """Open the relay WS, register, ping, and reconnect. Returns step results."""
    from websockets.asyncio.client import connect as ws_connect

    ws_url = _relay_ws_url(cloud_url)
    steps: dict[str, object] = {"ws_url": ws_url}

    async def _session() -> None:
        async with ws_connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {device_token}"},
            open_timeout=timeout,
            close_timeout=5,
        ) as ws:
            steps["connect"] = True
            hello = {
                "type": "hello",
                "models": models,
                "capabilities": ["chat", "models"],
                "client_version": "ollabridge-doctor",
                "platform": "doctor",
            }
            await ws.send(json.dumps(hello))
            steps["hello"] = True
            steps["models_sent"] = len(models)
            # App-level ping → pong (cloud answers {"type":"pong"})
            await ws.send(json.dumps({"type": "ping"}))
            try:
                deadline = time.time() + timeout
                while time.time() < deadline:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=max(0.1, deadline - time.time())
                    )
                    msg = json.loads(raw)
                    if msg.get("type") == "pong":
                        steps["pong"] = True
                        break
            except (asyncio.TimeoutError, json.JSONDecodeError):
                steps.setdefault("pong", False)

    await _session()
    # Reconnect test: a second session must also succeed.
    try:
        await _session()
        steps["reconnect"] = True
    except Exception as exc:
        steps["reconnect"] = False
        steps["reconnect_error"] = f"{type(exc).__name__}: {exc}"
    return steps


def _local_models() -> list[str]:
    try:
        r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            return [
                m.get("name", "") for m in r.json().get("models", []) if m.get("name")
            ]
    except Exception:
        pass
    return []


def check_relay(timeout: float = 10.0) -> SectionReport:
    sec = SectionReport(name="Relay")
    creds = load_cloud_device_credentials()
    if not creds:
        sec.add(
            CheckResult.fail(
                "Cloud credentials", "Cloud credentials not found.", hint=LOGIN_HINT
            )
        )
        return sec
    sec.add(CheckResult.ok("Cloud credentials", f"device {creds.device_id}"))

    models = _local_models()
    try:
        steps = asyncio.run(
            _relay_probe(creds.cloud_url, creds.device_token, models, timeout=timeout)
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        hint = "Check network / cloud URL"
        if "4401" in str(exc) or "401" in str(exc):
            detail = "credentials rejected (expired or revoked token)"
            hint = "Re-pair with:  ollabridge login"
        sec.add(CheckResult.fail("WSS connection established", detail, hint=hint))
        return sec

    sec.add(CheckResult.ok("WSS connection established", str(steps.get("ws_url", ""))))
    sec.add(CheckResult.ok("Device registered", "hello accepted"))
    sec.add(
        CheckResult.ok("Model list sent", f"{steps.get('models_sent', 0)} models")
        if models
        else CheckResult.warn(
            "Model list sent",
            "no local models detected to register",
            hint="Pull a model:  ollama pull llama3.1",
        )
    )
    if steps.get("pong"):
        sec.add(CheckResult.ok("Ping/pong", "app-level heartbeat OK"))
    else:
        sec.add(
            CheckResult.warn(
                "Ping/pong", "no app-level pong (WS-level keepalive still applies)"
            )
        )
    if steps.get("reconnect"):
        sec.add(CheckResult.ok("Reconnect test", "second connection accepted"))
    else:
        sec.add(
            CheckResult.fail(
                "Reconnect test", str(steps.get("reconnect_error", "failed"))
            )
        )

    # Does the cloud expose our local models? Requires a cloud API key.
    cloud_key = _cloud_api_key()
    if not cloud_key:
        sec.add(
            CheckResult.skip(
                "Cloud /v1/models includes local models",
                "set OLLABRIDGE_CLOUD_API_KEY to verify the cloud-side model list",
            )
        )
        return sec
    try:
        r = httpx.get(
            creds.cloud_url.rstrip("/") + "/v1/models",
            timeout=10,
            headers={"Authorization": f"Bearer {cloud_key}"},
        )
        r.raise_for_status()
        cloud_models = {m.get("id", "") for m in r.json().get("data", [])}
        visible = [m for m in models if m in cloud_models]
        if models and visible:
            sec.add(
                CheckResult.ok(
                    "Cloud /v1/models includes local models",
                    f"{len(visible)}/{len(models)} visible",
                )
            )
        elif models:
            sec.add(
                CheckResult.fail(
                    "Cloud /v1/models includes local models",
                    "none of the local models are visible in the cloud",
                    hint="Keep the gateway running so the relay stays registered",
                )
            )
        else:
            sec.add(
                CheckResult.skip(
                    "Cloud /v1/models includes local models",
                    "no local models to compare",
                )
            )
    except Exception as exc:
        sec.add(
            CheckResult.fail(
                "Cloud /v1/models includes local models", f"{type(exc).__name__}: {exc}"
            )
        )
    return sec


# ── Providers ───────────────────────────────────────────────────────────


def check_providers(probe: bool = False) -> SectionReport:
    from ollabridge.providers_meta import (
        PROVIDER_CATALOG,
        configured_provider_names,
        load_providers,
    )

    sec = SectionReport(name="Providers")
    configured = configured_provider_names()
    records = {r.name: r for r in load_providers()}

    if not configured and not records:
        sec.add(
            CheckResult.warn(
                "Providers configured",
                "no BYOK providers configured",
                hint="Run:  ollabridge providers add <provider>",
            )
        )
        return sec

    for name in sorted(configured | set(records)):
        spec = PROVIDER_CATALOG.get(
            records.get(name, None).kind if name in records else name
        ) or PROVIDER_CATALOG.get(name)
        rec = records.get(name)
        where = []
        if rec:
            where.append(rec.storage_mode.replace("_", " "))
        if spec and os.environ.get(spec.env_var, "").strip():
            where.append(f"env:{spec.env_var}")
        label = spec.label if spec else name
        if name in configured:
            sec.add(CheckResult.ok(f"{label} configured", ", ".join(where) or "local"))
        else:
            sec.add(
                CheckResult.warn(
                    f"{label} configured",
                    "metadata present but no key found",
                    hint=f"Run:  ollabridge providers add {name}",
                )
            )

    missing = [n for n in ("openai", "anthropic") if n not in configured]
    for n in missing:
        sec.add(
            CheckResult.warn(
                f"{PROVIDER_CATALOG[n].label} configured",
                "not configured",
                hint=f"Optional — run:  ollabridge providers add {n}",
            )
        )

    if probe:
        from ollabridge.provider_ops import test_provider

        for name in sorted(configured):
            ok, detail = test_provider(name)
            sec.add(
                CheckResult.ok(f"{name} health", detail)
                if ok
                else CheckResult.fail(f"{name} health", detail)
            )
    return sec


# ── Security ────────────────────────────────────────────────────────────


def check_security() -> SectionReport:
    sec = SectionReport(name="Security")

    # Secrets at rest
    try:
        from ollabridge.addons.providers.secret_store import SecretStore

        store = SecretStore()
        if store.is_encrypted:
            sec.add(
                CheckResult.ok(
                    "Secrets are not plaintext", "secrets.enc is Fernet-encrypted"
                )
            )
        elif store.list_keys():
            sec.add(
                CheckResult.fail(
                    "Secrets are not plaintext",
                    "OLLA_SECRET unset — provider keys stored plaintext (0o600)",
                    hint="export OLLA_SECRET=<random string> and re-add keys",
                )
            )
        else:
            sec.add(
                CheckResult.warn(
                    "Secrets are not plaintext",
                    "OLLA_SECRET unset (no secrets stored yet)",
                    hint="Set OLLA_SECRET before adding provider keys",
                )
            )
    except Exception as exc:
        sec.add(
            CheckResult.warn(
                "Secrets are not plaintext", f"{type(exc).__name__}: {exc}"
            )
        )

    # File permissions
    bad: list[str] = []
    for f in (
        paths.cloud_device_file(),
        paths.sync_file(),
        paths.providers_file(),
        paths.policies_file(),
        paths.traces_db_file(),
        paths.data_dir() / "secrets.enc",
    ):
        if f.exists() and not paths.permissions_ok(f):
            bad.append(f.name)
    if bad:
        sec.add(
            CheckResult.fail(
                "File permissions OK",
                f"world/group-readable: {', '.join(bad)}",
                hint=f"chmod 600 {paths.data_dir()}/<file>",
            )
        )
    else:
        sec.add(CheckResult.ok("File permissions OK", str(paths.data_dir())))

    # Auth posture
    mode = (settings.AUTH_MODE or "required").lower().strip()
    keys = [k.strip() for k in (settings.API_KEYS or "").split(",") if k.strip()]
    placeholder = any("change-me" in k or "dev-key" in k for k in keys)
    if mode == "required" and keys and not placeholder:
        sec.add(CheckResult.ok("Local API requires key", "AUTH_MODE=required"))
    elif placeholder:
        sec.add(
            CheckResult.fail(
                "Local API requires key",
                "API_KEYS contains a default placeholder key",
                hint="Set a real key:  API_KEYS=<key> (start generates one)",
            )
        )
    elif mode == "local-trust":
        sec.add(
            CheckResult.warn(
                "Local API requires key",
                "local-trust: loopback clients bypass auth",
                hint="Use AUTH_MODE=required for shared machines",
            )
        )
    else:
        sec.add(CheckResult.ok("Local API requires key", f"AUTH_MODE={mode}"))

    # CORS
    origins = [o.strip() for o in (settings.CORS_ORIGINS or "").split(",") if o.strip()]
    if not origins:
        sec.add(
            CheckResult.fail(
                "CORS configuration",
                "empty CORS_ORIGINS becomes wildcard '*'",
                hint="Set CORS_ORIGINS to explicit origins",
            )
        )
    elif all(o.startswith(("http://localhost", "http://127.0.0.1")) for o in origins):
        sec.add(CheckResult.warn("CORS configuration", "CORS allows localhost only"))
    else:
        sec.add(
            CheckResult.ok("CORS configuration", f"{len(origins)} explicit origins")
        )

    # Bind host
    if settings.HOST in ("0.0.0.0", "::"):
        sec.add(
            CheckResult.warn(
                "Bind host",
                "default bind is 0.0.0.0 (all interfaces)",
                hint="Use HOST=127.0.0.1 unless LAN access is intended",
            )
        )
    else:
        sec.add(CheckResult.ok("Bind host", settings.HOST))

    # Prompt logging default
    sync = load_sync_config()
    if sync.prompt_logging:
        sec.add(CheckResult.warn("Prompt logging", "enabled in sync.yaml"))
    else:
        sec.add(CheckResult.ok("Prompt logging", "off (default)"))

    if (settings.ENROLLMENT_SECRET or "").startswith("dev-"):
        sec.add(
            CheckResult.warn(
                "Enrollment secret",
                "default dev enrollment secret in use",
                hint="Set ENROLLMENT_SECRET for multi-node deployments",
            )
        )
    return sec
