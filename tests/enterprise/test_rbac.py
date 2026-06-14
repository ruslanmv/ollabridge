"""RBAC interface contracts: stable permission strings, fail-closed checks."""

from __future__ import annotations

from ollabridge.enterprise import (
    PERMISSIONS,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    permissions_for,
    role_allows,
)

REQUIRED_PERMISSIONS = {
    "models:read",
    "chat:invoke",
    "devices:pair",
    "devices:share",
    "providers:create",
    "providers:use",
    "providers:rotate",
    "logs:read",
    "audit:read",
    "billing:read",
    "policies:write",
    "org:admin",
}

REQUIRED_ROLES = {
    "owner",
    "admin",
    "developer",
    "viewer",
    "billing_admin",
    "security_auditor",
    "device_operator",
}


def test_required_permission_strings_exist():
    assert REQUIRED_PERMISSIONS == PERMISSIONS


def test_required_roles_exist():
    assert REQUIRED_ROLES == {r.value for r in Role}


def test_every_role_has_a_permission_set():
    for role in Role:
        assert role in ROLE_PERMISSIONS


def test_owner_has_everything():
    assert permissions_for(Role.OWNER) == frozenset(Permission)


def test_viewer_cannot_invoke_or_administer():
    assert not role_allows(Role.VIEWER, Permission.CHAT_INVOKE)
    assert not role_allows(Role.VIEWER, Permission.ORG_ADMIN)
    assert role_allows(Role.VIEWER, Permission.MODELS_READ)


def test_security_auditor_reads_audit_but_cannot_chat():
    assert role_allows("security_auditor", "audit:read")
    assert not role_allows("security_auditor", "chat:invoke")


def test_device_operator_scope():
    assert role_allows(Role.DEVICE_OPERATOR, Permission.DEVICES_PAIR)
    assert role_allows(Role.DEVICE_OPERATOR, Permission.DEVICES_SHARE)
    assert not role_allows(Role.DEVICE_OPERATOR, Permission.PROVIDERS_ROTATE)


def test_unknown_role_or_permission_fails_closed():
    assert permissions_for("superuser") == frozenset()
    assert role_allows("superuser", "org:admin") is False
    assert role_allows(Role.OWNER, "universe:destroy") is False
