"""Endpoint diagnosis: measure one chat or MCP endpoint and say how hard it
can be driven (``ollabridge diagnose``).

Additive and read-only. Nothing here runs unless the command is invoked; it
sends only harmless requests (a one-word chat prompt, MCP ``initialize`` /
``ping`` / ``tools/list``), under a hard budget of HTTP requests and seconds,
and stops raising the load at the first rate-limit answer or sign of
trouble. It changes no setting unless ``--apply`` is given.

See docs/ENDPOINT_DIAGNOSIS.md.
"""
