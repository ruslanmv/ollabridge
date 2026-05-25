"""Manual verification: exercise each hf:* alias end-to-end against the live
Hugging Face Inference Providers router.

Usage::

    HF_TOKEN=hf_xxx python scripts/verify_hf_inference.py

Resolves each alias through the gateway's ProviderRouter, sends a tiny chat
request, and prints which upstream provider answered and the response excerpt.

For vision (``hf:vision``) we pass a tiny image_url so the VLM is actually
exercised. Failures are reported but do not stop the run — every alias gets
attempted so a single unhealthy upstream doesn't mask the others.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ollabridge.addons.providers.services.provider_seeder import seed_providers


ALIASES_TO_TEST: list[tuple[str, str, list[dict[str, Any]]]] = [
    (
        "hf:best",
        "Best Hugging Face chat model based on catalog score",
        [{"role": "user", "content": "Reply with the single word: ping"}],
    ),
    (
        "hf:fast",
        "Lowest latency live HF chat model",
        [{"role": "user", "content": "Reply with the single word: ping"}],
    ),
    (
        "hf:cheap",
        "Lowest estimated cost model that still meets quality threshold",
        [{"role": "user", "content": "Reply with the single word: ping"}],
    ),
    (
        "hf:deepseek",
        "Best available DeepSeek-family HF route",
        [{"role": "user", "content": "Reply with the single word: ping"}],
    ),
    (
        "hf:vision",
        "Best VLM route supporting image inputs",
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What single colour dominates this image? Answer with just the colour name."},
                    {
                        "type": "image_url",
                        "image_url": {
                            # 1x1 red PNG.
                            "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
                        },
                    },
                ],
            }
        ],
    ),
]


def _excerpt(result: dict[str, Any]) -> str:
    try:
        return result["choices"][0]["message"]["content"][:120]
    except (KeyError, IndexError, TypeError):
        return "<unparseable response>"


async def _exercise(prouter, alias: str, label: str, messages: list[dict]) -> dict:
    candidates = prouter.resolve(alias)
    chosen_label = "<no route>"
    if candidates:
        chosen_label = f"{candidates[0].provider_id} → {candidates[0].model}"

    print(f"\n=== {alias}  —  {label}")
    print(f"    resolved → {chosen_label}")

    if not candidates:
        return {"alias": alias, "ok": False, "error": "no route resolved"}

    started = time.monotonic()
    try:
        result = await prouter.route_chat(alias, messages, max_tokens=12)
        latency_ms = (time.monotonic() - started) * 1000.0
        print(f"    ok ({latency_ms:.0f} ms): {_excerpt(result)!r}")
        return {"alias": alias, "ok": True, "latency_ms": latency_ms,
                "model": result.get("model"), "excerpt": _excerpt(result)}
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.monotonic() - started) * 1000.0
        print(f"    FAILED ({latency_ms:.0f} ms): {type(exc).__name__}: {exc}")
        return {"alias": alias, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


async def main() -> int:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY")
    if not token:
        print("HF_TOKEN is not set; cannot verify live inference.")
        return 2

    registry, prouter = await seed_providers()
    # Inject the live token into the HF adapter.
    adapter = registry.get_adapter("huggingface-free")
    if adapter is None:
        print("huggingface-free adapter not registered — check providers.seed.yaml")
        return 2
    adapter.api_key = token
    print(f"HF adapter token: ...{token[-6:]}")

    results: list[dict] = []
    for alias, label, messages in ALIASES_TO_TEST:
        results.append(await _exercise(prouter, alias, label, messages))

    ok_count = sum(1 for r in results if r["ok"])
    print(f"\n--- summary: {ok_count}/{len(results)} aliases responded ---")
    for r in results:
        marker = "OK  " if r["ok"] else "FAIL"
        print(f"  {marker}  {r['alias']:<14}  {r.get('error') or r.get('model') or ''}")
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
