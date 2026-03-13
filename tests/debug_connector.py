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

import requests

TIMEOUT = 12


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
    timeout: int = TIMEOUT,
) -> Tuple[bool, Optional[int], Any, float]:
    started = time.perf_counter()
    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=auth_headers(api_key),
            json=json_body,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - started
        return resp.ok, resp.status_code, safe_json(resp), elapsed
    except requests.RequestException as e:
        elapsed = time.perf_counter() - started
        return False, None, str(e), elapsed


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

    hp_health_ok = test_health(args.homepilot_base, "HomePilot", api_key=args.homepilot_key)
    hp_models = test_models(args.homepilot_base, "HomePilot", api_key=args.homepilot_key) if hp_health_ok else []

    ob_health_ok = test_health(args.ollabridge_base, "OllaBridge", api_key=args.ollabridge_key)
    ob_models = test_models(args.ollabridge_base, "OllaBridge", api_key=args.ollabridge_key) if ob_health_ok else []

    if hp_models and ob_models:
        compare_homepilot_visibility(hp_models, ob_models)

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

    print_section("Recommended checks")
    print(
        "- If HomePilot works directly but persona models are missing in OllaBridge,\n"
        "  the issue is likely in the OllaBridge HomePilot source registration/config.\n"
        "- If /v1/models works but /v1/chat/completions fails, check auth, model naming, and routing.\n"
        "- If usage is not returned, lightweight request accounting in OllaBridge will improve monitoring."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())