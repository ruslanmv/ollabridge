#!/usr/bin/env python3
"""
Provider smoke-test runner for OllaBridge Cloud.

Loads the provider seed catalog and test matrix, then runs a single
chat request against each test scenario. Reports latency and pass/fail.

Usage:
    python scripts/test_providers.py
    python scripts/test_providers.py --seed path/to/providers.seed.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ollabridge.addons.providers.services.provider_loader import (
    load_provider_seed,
    load_test_matrix,
)
from ollabridge.addons.providers.services.provider_seeder import (
    seed_providers,
)


def _fmt_status(ok: bool) -> str:
    return "\033[92mOK\033[0m" if ok else "\033[91mFAIL\033[0m"


async def run_tests(seed_path: str | None = None) -> None:
    # Initialize the provider system
    registry, router = await seed_providers(seed_path)

    # Load test matrix
    tests = load_test_matrix()
    if not tests:
        print("No test scenarios found in test-matrix.yaml")
        return

    print()
    print(f"{'Provider':<20} {'Status':<10} {'Latency':<12} {'Tier':<12} {'Notes'}")
    print("-" * 78)

    passed = 0
    failed = 0

    for test in tests:
        provider_id = test.get("provider", "")
        model = test.get("model", "")
        prompt = test.get("prompt", "Hello")

        config = registry.get_config(provider_id)
        if not config:
            print(f"{provider_id:<20} {'SKIP':<10} {'—':<12} {'—':<12} provider not registered")
            continue

        adapter = registry.get_adapter(provider_id)
        if not adapter:
            print(f"{provider_id:<20} {'SKIP':<10} {'—':<12} {'—':<12} no adapter")
            continue

        messages = [{"role": "user", "content": prompt}]
        start = time.monotonic()
        try:
            result = await adapter.chat(model, messages)
            latency_ms = (time.monotonic() - start) * 1000
            content = ""
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")[:50]

            ok = bool(content)
            status = _fmt_status(ok)
            if ok:
                passed += 1
            else:
                failed += 1
            print(f"{provider_id:<20} {status:<18} {latency_ms:>7.0f}ms    {config.tier.value:<12} {config.notes[:30]}")

        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            failed += 1
            status = _fmt_status(False)
            print(f"{provider_id:<20} {status:<18} {latency_ms:>7.0f}ms    {config.tier.value:<12} {str(exc)[:40]}")

    print("-" * 78)
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    print()


def main():
    parser = argparse.ArgumentParser(description="OllaBridge Cloud provider smoke tests")
    parser.add_argument("--seed", help="Path to providers.seed.yaml", default=None)
    args = parser.parse_args()
    asyncio.run(run_tests(args.seed))


if __name__ == "__main__":
    main()
