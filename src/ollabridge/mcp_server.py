"""Backwards-compatible MCP entrypoint.

The MCP implementation moved to :mod:`ollabridge.mcp.server`.
"""

from __future__ import annotations

from ollabridge.mcp.server import main


if __name__ == "__main__":
    main()
