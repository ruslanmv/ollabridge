"""Enterprise interfaces: RBAC roles/permissions and admin model contracts.

These are the local definitions the OllaBridge Cloud control plane enforces
as its admin model matures. Nothing here fakes unimplemented behavior — the
local gateway uses them for documentation, validation, and future scoped
API keys. See docs/ENTERPRISE.md.
"""

from ollabridge.enterprise.rbac import (  # noqa: F401
    PERMISSIONS,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    permissions_for,
    role_allows,
)
