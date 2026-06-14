"""Policy engine: validation, alias resolution, and honest route explanation."""

from __future__ import annotations

import pytest

from ollabridge.core import paths
from ollabridge.policies import (
    BUILTIN_ALIASES,
    RouteContext,
    explain_route,
    find_policy,
    load_policies,
    validate_policies_file,
)


def test_builtin_aliases_all_resolve():
    pols = load_policies()
    for alias in BUILTIN_ALIASES:
        assert find_policy(alias, pols) is not None, alias


def test_validate_missing_file_is_ok():
    assert validate_policies_file() == []


def test_validate_rejects_bad_yaml():
    paths.policies_file().write_text("policies: [unclosed", encoding="utf-8")
    problems = validate_policies_file()
    assert problems and "YAML" in problems[0]


def test_validate_rejects_bad_schema():
    paths.policies_file().write_text(
        "policies:\n  - name: broken\n    match: {}\n", encoding="utf-8"
    )
    problems = validate_policies_file()
    assert problems


def test_validate_flags_no_target_with_fallback_disabled():
    paths.policies_file().write_text(
        "policies:\n"
        "  - name: dead_end\n"
        "    match: {alias: dead}\n"
        "    route: {fallback: false}\n",
        encoding="utf-8",
    )
    problems = validate_policies_file()
    assert any("fallback disabled" in p for p in problems)


def test_user_policy_overrides_builtin_alias():
    paths.policies_file().write_text(
        "policies:\n"
        "  - name: my_cheap\n"
        "    match: {alias: cheap}\n"
        "    route:\n"
        "      prefer: [{provider: deepseek}]\n",
        encoding="utf-8",
    )
    pol = find_policy("cheap")
    assert pol is not None and pol.name == "my_cheap"


@pytest.fixture
def ctx_local_only():
    return RouteContext(
        local_models=["llama3.1:8b", "qwen2.5-coder:14b"],
        local_device_name="Test PC",
        configured_providers=set(),
    )


def test_local_private_selects_local_and_never_providers(ctx_local_only):
    exp = explain_route("local-private", context=ctx_local_only)
    assert exp.selected_backend == "local_device"
    assert exp.selected_model == "llama3.1:8b"
    assert exp.selected_provider is None
    assert exp.prompt_logging is False
    assert exp.estimated_cost_usd_per_1k_tokens == 0.0


def test_local_private_with_no_models_fails_closed():
    exp = explain_route("local-private", context=RouteContext(local_models=[]))
    assert exp.selected_backend is None
    assert "fallback is disabled" in (exp.error or "")


def test_best_prefers_provider_when_configured():
    ctx = RouteContext(local_models=["llama3"], configured_providers={"anthropic"})
    exp = explain_route("best", context=ctx)
    assert exp.selected_backend == "provider:anthropic"
    assert exp.selected_provider == "anthropic"
    assert (
        exp.estimated_cost_usd_per_1k_tokens
        and exp.estimated_cost_usd_per_1k_tokens > 0
    )


def test_best_falls_back_to_local_when_no_providers(ctx_local_only):
    exp = explain_route("best", context=ctx_local_only)
    assert exp.selected_backend == "local_device"
    # skipped providers must be explained
    assert any("no credential configured" in r for r in exp.reasons)


def test_cheap_respects_cost_ceiling():
    # anthropic is too expensive for cheap_mode's $0.01/1k ceiling even if
    # it were preferred; groq fits under it.
    ctx = RouteContext(local_models=[], configured_providers={"groq"})
    exp = explain_route("cheap", context=ctx)
    assert exp.selected_backend == "provider:groq"
    assert exp.estimated_cost_usd_per_1k_tokens is not None
    assert exp.estimated_cost_usd_per_1k_tokens <= 0.01


def test_direct_local_model_request(ctx_local_only):
    exp = explain_route("qwen2.5-coder:14b", context=ctx_local_only)
    assert exp.selected_backend == "local_device"
    assert exp.policy_name is None


def test_unknown_model_is_passed_through(ctx_local_only):
    exp = explain_route("gpt-99-ultra", context=ctx_local_only)
    assert exp.selected_backend is None
    assert exp.error


def test_deny_filter_blocks_provider():
    paths.policies_file().write_text(
        "policies:\n"
        "  - name: no_openai\n"
        "    match: {alias: locked}\n"
        "    route:\n"
        "      deny: [{provider: openai}]\n"
        "      prefer: [{provider: openai}, {provider: groq}]\n",
        encoding="utf-8",
    )
    ctx = RouteContext(configured_providers={"openai", "groq"})
    exp = explain_route("locked", context=ctx)
    assert exp.selected_backend == "provider:groq"
    assert any("denied by policy" in r for r in exp.reasons)


def test_prefix_model_matching_for_local():
    paths.policies_file().write_text(
        "policies:\n"
        "  - name: pin_model\n"
        "    match: {alias: pinned}\n"
        "    route:\n"
        "      prefer: [{provider: local, model: 'llama3.1'}]\n",
        encoding="utf-8",
    )
    ctx = RouteContext(local_models=["llama3.1:8b"])
    exp = explain_route("pinned", context=ctx)
    assert exp.selected_model == "llama3.1:8b"
