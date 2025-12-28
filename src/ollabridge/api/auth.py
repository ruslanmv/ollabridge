from __future__ import annotations

from fastapi import Depends
from ollabridge.core.security import require_api_key

# Backwards-compatible alias used by existing routes.
AuthDep = Depends(require_api_key)
