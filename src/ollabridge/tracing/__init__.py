"""Request tracing: every request gets a request_id and a metadata-only trace.

Prompt and response content are NEVER stored here. See docs/PRIVACY.md.
"""

from ollabridge.tracing.store import (
    TraceRecord,
    TraceStore,
    get_trace_store,
)  # noqa: F401
