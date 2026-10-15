"""Suite-wide isolation for process-level state.

The reachability monitor is a module singleton on purpose (one outage, one
warning across every caller), which means a test that drives Ollama "down"
would otherwise leave the next test starting mid-outage, with its first
failure logged at DEBUG instead of WARNING.
"""

from __future__ import annotations

import pytest

from ollabridge.core import reachability


@pytest.fixture(autouse=True)
def _fresh_reachability_state():
    reachability.OLLAMA.reset()
    yield
    reachability.OLLAMA.reset()
