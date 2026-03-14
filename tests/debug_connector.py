#!/usr/bin/env python3
"""
Lightweight HomePilot <-> OllaBridge connector debugger.

Defaults are tuned for local development:

HomePilot:
  http://localhost:8000

OllaBridge:
  http://localhost:11435

Usage:
  python tests/debug_connector.py

Optional:
  python tests/debug_connector.py --homepilot-key my-secret --ollabridge-key sk-...
  python tests/debug_connector.py --homepilot-model personality:assistant
  python tests/debug_connector.py --prompt "Say connector test successful."

Requires:
  pip install requests
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

TIMEOUT = 12


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def print_ok(msg: str) -> None:
    print(f"[OK] {msg}")


def print_warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def print_err(msg: str) -> None:
    print(f"[ERR] {msg}")


def print_skip(msg: str) -> None:
    print(f"[SKIP] {msg}")


def auth_headers(api_key: Optional[str]) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    return headers


def safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def request_json(
    method: str,
    url: str,
    api_key: Optional[str] = None,
    json_body: Optional[Dict[str, Any]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    timeout: int = TIMEOUT,
) -> Tuple[bool, Optional[int], Any, float]:
    started = time.perf_counter()
    try:
        hdrs = auth_headers(api_key)
        if extra_headers:
            hdrs.update(extra_headers)
        resp = requests.request(
            method=method,
            url=url,
            headers=hdrs,
            json=json_body,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - started
        return resp.ok, resp.status_code, safe_json(resp), elapsed
    except requests.RequestException as e:
        elapsed = time.perf_counter() - started
        return False, None, str(e), elapsed


# ---------------------------------------------------------------------------
# Core checks (unchanged logic)
# ---------------------------------------------------------------------------

def test_health(base_url: str, label: str, api_key: Optional[str] = None) -> bool:
    print_section(f"{label}: /health")
    ok, status, data, elapsed = request_json(
        "GET", f"{base_url.rstrip('/')}/health", api_key=api_key
    )
    if ok:
        print_ok(f"{label} health reachable in {elapsed:.2f}s")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return True

    print_err(f"{label} health failed (status={status}, time={elapsed:.2f}s)")
    print(data)
    return False


def extract_model_ids(models_payload: Any) -> List[str]:
    if isinstance(models_payload, dict) and isinstance(models_payload.get("data"), list):
        result: List[str] = []
        for item in models_payload["data"]:
            if isinstance(item, dict) and "id" in item:
                result.append(str(item["id"]))
        return result
    return []


def split_model_groups(model_ids: List[str]) -> Tuple[List[str], List[str]]:
    personas = [m for m in model_ids if m.startswith("persona:") or m.startswith("personality:")]
    standard = [m for m in model_ids if m not in personas]
    return standard, personas


def test_models(base_url: str, label: str, api_key: Optional[str] = None) -> List[str]:
    print_section(f"{label}: /v1/models")
    ok, status, data, elapsed = request_json(
        "GET", f"{base_url.rstrip('/')}/v1/models", api_key=api_key
    )
    if not ok:
        print_err(f"{label} models failed (status={status}, time={elapsed:.2f}s)")
        print(data)
        return []

    model_ids = extract_model_ids(data)
    standard, personas = split_model_groups(model_ids)

    print_ok(f"{label} returned {len(model_ids)} model(s) in {elapsed:.2f}s")
    print(f"  Standard models: {len(standard)}")
    print(f"  Persona models:  {len(personas)}")

    if standard:
        print("\n  Standard:")
        for model_id in standard[:20]:
            print(f"   - {model_id}")

    if personas:
        print("\n  Personas:")
        for model_id in personas[:20]:
            print(f"   - {model_id}")

    return model_ids


def choose_model(preferred: Optional[str], models: List[str], prefer_persona: bool) -> Optional[str]:
    if preferred:
        return preferred

    if prefer_persona:
        for model_id in models:
            if model_id.startswith("persona:") or model_id.startswith("personality:"):
                return model_id

    return models[0] if models else None


def estimate_tokens_from_text(text: str) -> int:
    return max(1, len(text) // 4)


def extract_reply_text(chat_payload: Any) -> str:
    try:
        return str(chat_payload["choices"][0]["message"]["content"])
    except Exception:
        return ""


def test_chat(
    base_url: str,
    label: str,
    api_key: Optional[str],
    model: str,
    prompt: str,
) -> bool:
    print_section(f"{label}: /v1/chat/completions")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise connectivity test assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 120,
        "stream": False,
    }

    ok, status, data, elapsed = request_json(
        "POST",
        f"{base_url.rstrip('/')}/v1/chat/completions",
        api_key=api_key,
        json_body=payload,
        timeout=30,
    )

    if not ok:
        print_err(f"{label} chat failed (status={status}, time={elapsed:.2f}s)")
        if isinstance(data, (dict, list)):
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(data)
        return False

    reply = extract_reply_text(data)
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    est_tokens = estimate_tokens_from_text(reply)

    print_ok(f"{label} chat succeeded in {elapsed:.2f}s using model '{model}'")

    print("\nReply:")
    print("-" * 80)
    print(reply[:800] if reply else "<empty>")
    print("-" * 80)

    if usage:
        print("\nReported usage:")
        print(json.dumps(usage, indent=2, ensure_ascii=False))
    else:
        print_warn(f"{label} did not return usage; estimated completion tokens ≈ {est_tokens}")

    return True


def compare_homepilot_visibility(homepilot_models: List[str], ollabridge_models: List[str]) -> None:
    print_section("Connector visibility analysis")

    hp_personas = {
        m for m in homepilot_models
        if m.startswith("persona:") or m.startswith("personality:")
    }
    ob_personas = {
        m for m in ollabridge_models
        if m.startswith("persona:") or m.startswith("personality:")
    }

    shared = sorted(hp_personas & ob_personas)
    missing = sorted(hp_personas - ob_personas)

    print(f"HomePilot persona models: {len(hp_personas)}")
    print(f"OllaBridge persona models: {len(ob_personas)}")
    print(f"Shared persona models:     {len(shared)}")

    if shared:
        print_ok("OllaBridge can see HomePilot persona models.")
        for model_id in shared[:20]:
            print(f"  - {model_id}")

    if missing:
        print_warn("Some HomePilot persona models are NOT visible through OllaBridge:")
        for model_id in missing[:20]:
            print(f"  - {model_id}")
        print_warn("Check OllaBridge HomePilot source configuration and auth.")


# ---------------------------------------------------------------------------
# NEW: Workflow debug checks
# ---------------------------------------------------------------------------

def test_cors_preflight(base_url: str, label: str, model: str, api_key: Optional[str]) -> bool:
    """Simulate the browser CORS preflight (OPTIONS) that 3D-Avatar sends
    before fetching persona context.  A 400/405 here means the server
    doesn't handle OPTIONS on that route — browsers will block the real GET.
    """
    print_section(f"{label}: CORS preflight for /v1/persona/context/{{model}}")

    encoded_model = quote(model, safe="")
    url = f"{base_url.rstrip('/')}/v1/persona/context/{encoded_model}"

    print(f"  URL: OPTIONS {url}")
    print(f"  (simulates browser preflight with Authorization header)")

    started = time.perf_counter()
    try:
        resp = requests.options(
            url,
            headers={
                "Origin": "http://localhost:8080",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,accept",
            },
            timeout=TIMEOUT,
        )
        elapsed = time.perf_counter() - started
    except requests.RequestException as e:
        elapsed = time.perf_counter() - started
        print_err(f"OPTIONS request failed ({elapsed:.2f}s): {e}")
        return False

    if resp.ok:
        print_ok(f"CORS preflight succeeded (status={resp.status_code}, {elapsed:.2f}s)")
        acao = resp.headers.get("access-control-allow-origin", "<missing>")
        acah = resp.headers.get("access-control-allow-headers", "<missing>")
        print(f"  Access-Control-Allow-Origin:  {acao}")
        print(f"  Access-Control-Allow-Headers: {acah}")
        return True

    print_err(f"CORS preflight FAILED (status={resp.status_code}, {elapsed:.2f}s)")
    print(f"  Response: {resp.text[:300]}")
    print()
    print_warn(
        "FIX: The endpoint's require_api_key dependency runs before\n"
        "  CORSMiddleware can intercept OPTIONS.  Add an explicit\n"
        "  @app.options('/v1/persona/context/{{model:path}}') handler\n"
        "  that returns 200 with no auth check."
    )
    return False


def test_persona_context_get(base_url: str, label: str, model: str, api_key: Optional[str]) -> bool:
    """Test the actual GET /v1/persona/context/{model} endpoint."""
    print_section(f"{label}: GET /v1/persona/context/{{model}}")

    encoded_model = quote(model, safe="")
    url = f"{base_url.rstrip('/')}/v1/persona/context/{encoded_model}"
    print(f"  URL: GET {url}")

    ok, status, data, elapsed = request_json("GET", url, api_key=api_key)

    if not ok:
        print_err(f"Persona context GET failed (status={status}, {elapsed:.2f}s)")
        if isinstance(data, (dict, list)):
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(str(data)[:300])
        return False

    print_ok(f"Persona context returned in {elapsed:.2f}s")

    if isinstance(data, dict):
        ctx_ok = data.get("ok", False)
        ctx = data.get("context", {})
        err = data.get("error")
        if ctx_ok:
            print_ok(f"Context has {len(ctx)} key(s): {', '.join(sorted(ctx.keys())[:10])}")
        else:
            print_warn(f"Context returned ok=false, error={err}")
            if err == "no_node_for_model":
                print_warn("  -> OllaBridge cannot route this model to any HomePilot node.")
            elif err == "not_a_persona_model":
                print_warn("  -> Model exists but is not a persona/personality type.")
    else:
        print(str(data)[:300])

    return True


def test_homepilot_personality_api(base_url: str, api_key: Optional[str], personality_id: str) -> bool:
    """Test HomePilot's /api/personalities/{id} endpoint (used by compat layer)."""
    print_section(f"HomePilot: GET /api/personalities/{personality_id}")

    url = f"{base_url.rstrip('/')}/api/personalities/{personality_id}"
    ok, status, data, elapsed = request_json("GET", url, api_key=api_key)

    if not ok:
        print_err(f"Personality API failed (status={status}, {elapsed:.2f}s)")
        if isinstance(data, (dict, list)):
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(str(data)[:300])
        return False

    print_ok(f"Personality '{personality_id}' fetched in {elapsed:.2f}s")
    if isinstance(data, dict):
        name = data.get("name", data.get("id", "?"))
        has_prompt = bool(data.get("system_prompt"))
        print(f"  Name:          {name}")
        print(f"  System prompt: {'yes' if has_prompt else 'no'}")
    return True


def test_homepilot_persona_memory(base_url: str, api_key: Optional[str], project_id: str) -> bool:
    """Test HomePilot's /persona/memory endpoint for a persona project."""
    print_section(f"HomePilot: GET /persona/memory (project={project_id})")

    for category in ("fact", "preference"):
        url = f"{base_url.rstrip('/')}/persona/memory?project_id={project_id}&category={category}"
        ok, status, data, elapsed = request_json("GET", url, api_key=api_key)

        if not ok:
            print_err(f"Memory ({category}) failed (status={status}, {elapsed:.2f}s)")
            if isinstance(data, (dict, list)):
                print(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                print(str(data)[:300])
            return False

        count = len(data) if isinstance(data, list) else "?"
        print_ok(f"Memory category='{category}': {count} entries ({elapsed:.2f}s)")

    return True


def test_chat_with_context_header(
    base_url: str,
    label: str,
    api_key: Optional[str],
    model: str,
    prompt: str,
) -> bool:
    """Send a chat request with X-Include-Persona-Context header.
    This is what the 3D-Avatar sends when use_remote_prompt is enabled.
    Check whether the response includes x_persona_context inline.
    """
    print_section(f"{label}: chat with X-Include-Persona-Context")

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 120,
        "stream": False,
    }

    ok, status, data, elapsed = request_json(
        "POST",
        f"{base_url.rstrip('/')}/v1/chat/completions",
        api_key=api_key,
        json_body=payload,
        extra_headers={"X-Include-Persona-Context": "true"},
        timeout=30,
    )

    if not ok:
        print_err(f"Chat with context header failed (status={status}, {elapsed:.2f}s)")
        return False

    reply = extract_reply_text(data)
    print_ok(f"Chat succeeded in {elapsed:.2f}s using model '{model}'")

    # Check for inline persona context in the response
    has_ctx = False
    if isinstance(data, dict):
        if "x_persona_context" in data:
            has_ctx = True
            ctx = data["x_persona_context"]
            print_ok(f"Response includes x_persona_context ({len(ctx)} key(s))")
        else:
            print_warn("Response does NOT include x_persona_context.")
            print_warn("  The server may not support inline context injection yet.")

    print(f"\n  Reply preview: {reply[:120]}...")
    return True


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_runtime_defaults(args: argparse.Namespace) -> None:
    print_section("Using local defaults")
    print(f"HomePilot base:   {args.homepilot_base}")
    print(f"OllaBridge base:  {args.ollabridge_base}")
    print(f"HomePilot key:    {'set' if args.homepilot_key else 'not set'}")
    print(f"OllaBridge key:   {'set' if args.ollabridge_key else 'not set'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug HomePilot and OllaBridge connector state.")

    parser.add_argument(
        "--homepilot-base",
        default=os.getenv("HOMEPILOT_BASE", "http://localhost:8000"),
        help="HomePilot base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--homepilot-key",
        default=os.getenv("HOMEPILOT_API_KEY", "my-secret"),
        help="HomePilot shared API key (default: my-secret)",
    )
    parser.add_argument(
        "--homepilot-model",
        default=os.getenv("HOMEPILOT_MODEL"),
        help="Optional explicit HomePilot model to test",
    )

    parser.add_argument(
        "--ollabridge-base",
        default=os.getenv("OLLABRIDGE_BASE", "http://localhost:11435"),
        help="OllaBridge base URL (default: http://localhost:11435)",
    )
    parser.add_argument(
        "--ollabridge-key",
        default=os.getenv("OLLABRIDGE_API_KEY"),
        help="OllaBridge API key (default: from env only)",
    )
    parser.add_argument(
        "--ollabridge-model",
        default=os.getenv("OLLABRIDGE_MODEL"),
        help="Optional explicit OllaBridge model to test",
    )
    parser.add_argument(
        "--prompt",
        default="Reply exactly: connector test successful. Then mention which model you used.",
        help="Prompt used for chat testing",
    )

    args = parser.parse_args()
    print_runtime_defaults(args)

    issues: List[str] = []

    # --- Phase 1: Health ---
    hp_health_ok = test_health(args.homepilot_base, "HomePilot", api_key=args.homepilot_key)
    hp_models = test_models(args.homepilot_base, "HomePilot", api_key=args.homepilot_key) if hp_health_ok else []

    ob_health_ok = test_health(args.ollabridge_base, "OllaBridge", api_key=args.ollabridge_key)
    ob_models = test_models(args.ollabridge_base, "OllaBridge", api_key=args.ollabridge_key) if ob_health_ok else []

    if hp_models and ob_models:
        compare_homepilot_visibility(hp_models, ob_models)

    # --- Phase 2: Basic chat ---
    hp_model = choose_model(args.homepilot_model, hp_models, prefer_persona=True)
    ob_model = choose_model(args.ollabridge_model, ob_models, prefer_persona=True)

    if hp_model:
        test_chat(
            base_url=args.homepilot_base,
            label="HomePilot",
            api_key=args.homepilot_key,
            model=hp_model,
            prompt=args.prompt,
        )
    else:
        print_warn("Skipping HomePilot chat test because no model was found.")

    if ob_model:
        test_chat(
            base_url=args.ollabridge_base,
            label="OllaBridge",
            api_key=args.ollabridge_key,
            model=ob_model,
            prompt=args.prompt,
        )
    else:
        print_warn("Skipping OllaBridge chat test because no model was found.")
        print_warn("Tip: if OllaBridge requires auth, pass --ollabridge-key or set OLLABRIDGE_API_KEY.")

    # --- Phase 3: Workflow checks ---
    # Pick a persona model to test the full persona workflow
    persona_model = None
    personality_model = None
    for m in (ob_models or hp_models):
        if m.startswith("persona:") and not persona_model:
            persona_model = m
        if m.startswith("personality:") and not personality_model:
            personality_model = m

    test_model = persona_model or personality_model

    if test_model and ob_health_ok:
        # 3a. CORS preflight on OllaBridge
        cors_ok = test_cors_preflight(
            args.ollabridge_base, "OllaBridge", test_model, args.ollabridge_key,
        )
        if not cors_ok:
            issues.append(
                "CORS preflight (OPTIONS) on /v1/persona/context fails.\n"
                "  Browsers will block persona context fetches from 3D-Avatar."
            )

        # 3b. GET persona context on OllaBridge
        ctx_ok = test_persona_context_get(
            args.ollabridge_base, "OllaBridge", test_model, args.ollabridge_key,
        )
        if not ctx_ok:
            issues.append(
                "GET /v1/persona/context failed on OllaBridge.\n"
                "  Avatar won't receive voice/emotion/memory data."
            )

        # 3c. Chat with X-Include-Persona-Context header
        test_chat_with_context_header(
            args.ollabridge_base, "OllaBridge", args.ollabridge_key,
            test_model, args.prompt,
        )
    else:
        print_skip("Skipping persona workflow checks (no persona model or OllaBridge unreachable).")

    # 3d. HomePilot personality API
    if personality_model and hp_health_ok:
        pid = personality_model.split(":", 1)[1]  # e.g. "sexy" from "personality:sexy"
        hp_personality_ok = test_homepilot_personality_api(
            args.homepilot_base, args.homepilot_key, pid,
        )
        if not hp_personality_ok:
            issues.append(f"HomePilot /api/personalities/{pid} failed.")

    # 3e. HomePilot persona memory
    if persona_model and hp_health_ok:
        pid = persona_model.split(":", 1)[1]  # e.g. "lina--f9d4debf"
        mem_ok = test_homepilot_persona_memory(
            args.homepilot_base, args.homepilot_key, pid,
        )
        if not mem_ok:
            issues.append(f"HomePilot /persona/memory failed for project={pid}.")

    # --- Phase 4: Shared API publishing analysis ---
    if hp_models:
        print_section("Shared API publishing analysis")
        published = [m for m in hp_models if m.startswith("persona:")]
        personalities = [m for m in hp_models if m.startswith("personality:")]
        print(f"Published persona models: {len(published)}")
        print(f"Built-in personalities:   {len(personalities)}")
        if published:
            print("Published personas (via shared_api toggle):")
            for m in sorted(published):
                print(f"  - {m}")
        else:
            print_warn("No persona projects are published to the shared API.")
            print_warn("Enable 'Publish as API Model' in each persona's settings to expose it.")

    # --- Phase 5: Summary ---
    print_section("Workflow issue summary")
    if issues:
        for i, issue in enumerate(issues, 1):
            print(f"\n  {i}. {issue}")
        print()
    else:
        print_ok("No workflow issues detected.")

    print_section("Recommended checks")
    print(
        "- If HomePilot works directly but persona models are missing in OllaBridge,\n"
        "  the issue is likely in the OllaBridge HomePilot source registration/config.\n"
        "- If /v1/models works but /v1/chat/completions fails, check auth, model naming, and routing.\n"
        "- If usage is not returned, lightweight request accounting in OllaBridge will improve monitoring.\n"
        "- If persona models are missing, check 'Publish as API Model' toggle in persona settings.\n"
        "- If CORS preflight fails, add an explicit OPTIONS handler to the persona context route.\n"
        "- If agent loop falls back to direct LLM, check that agent_chat exports match the compat caller."
    )

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
