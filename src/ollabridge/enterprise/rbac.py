"""RBAC roles and permission strings for the OllaBridge enterprise model.

The cloud control plane currently enforces a coarser model
(``org_admin | member | viewer`` in ``ollabridge-cloud``); these definitions
are the target contract both sides converge on. Permission strings are
``<resource>:<action>`` and are stable identifiers — never rename, only add.
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet


class Permission(str, Enum):
    MODELS_READ = "models:read"
    CHAT_INVOKE = "chat:invoke"
    DEVICES_PAIR = "devices:pair"
    DEVICES_SHARE = "devices:share"
    PROVIDERS_CREATE = "providers:create"
    PROVIDERS_USE = "providers:use"
    PROVIDERS_ROTATE = "providers:rotate"
    LOGS_READ = "logs:read"
    AUDIT_READ = "audit:read"
    BILLING_READ = "billing:read"
    POLICIES_WRITE = "policies:write"
    ORG_ADMIN = "org:admin"


PERMISSIONS: FrozenSet[str] = frozenset(p.value for p in Permission)


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"
    BILLING_ADMIN = "billing_admin"
    SECURITY_AUDITOR = "security_auditor"
    DEVICE_OPERATOR = "device_operator"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.ADMIN: frozenset(Permission) - {Permission.BILLING_READ},
    Role.DEVELOPER: frozenset(
        {
            Permission.MODELS_READ,
            Permission.CHAT_INVOKE,
            Permission.DEVICES_PAIR,
            Permission.PROVIDERS_USE,
            Permission.LOGS_READ,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.MODELS_READ,
            Permission.LOGS_READ,
        }
    ),
    Role.BILLING_ADMIN: frozenset(
        {
            Permission.BILLING_READ,
            Permission.MODELS_READ,
        }
    ),
    Role.SECURITY_AUDITOR: frozenset(
        {
            Permission.AUDIT_READ,
            Permission.LOGS_READ,
            Permission.MODELS_READ,
        }
    ),
    Role.DEVICE_OPERATOR: frozenset(
        {
            Permission.DEVICES_PAIR,
            Permission.DEVICES_SHARE,
            Permission.MODELS_READ,
        }
    ),
}


def permissions_for(role: Role | str) -> frozenset[Permission]:
    """Permissions granted to *role*; unknown roles get nothing."""
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except (ValueError, KeyError):
        return frozenset()


def role_allows(role: Role | str, permission: Permission | str) -> bool:
    """True when *role* grants *permission* (fail-closed on unknowns)."""
    try:
        perm = Permission(permission)
    except ValueError:
        return False
    return perm in permissions_for(role)
