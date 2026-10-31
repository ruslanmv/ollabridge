"""Suite-wide isolation for process-level state.

Data directory: every OllaBridge store (runtime settings, the request
database, traces, secrets, catalogs, pairing tokens, sessions) lives under
``OLLABRIDGE_HOME``. Several of them resolve that once, when the settings
singleton is imported, so the variable is set here, before anything imports
``ollabridge``, to a directory this session owns. Without it a test run wrote
request rows and traces into the developer's real ``~/.ollabridge``.

The reachability monitor is a module singleton on purpose (one outage, one
warning across every caller), which means a test that drives Ollama "down"
would otherwise leave the next test starting mid-outage, with its first
failure logged at DEBUG instead of WARNING.
"""

from __future__ import annotations

import gc
import os
import shutil
import tempfile
from pathlib import Path

_PREFIX = "ollabridge-tests-"
_TEST_HOME = Path(tempfile.mkdtemp(prefix=_PREFIX))
os.environ["OLLABRIDGE_HOME"] = str(_TEST_HOME)

import pytest  # noqa: E402

from ollabridge.core import reachability  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_reachability_state():
    reachability.OLLAMA.reset()
    yield
    reachability.OLLAMA.reset()


def pytest_sessionfinish(session, exitstatus):
    # Windows will not delete open files: release the request database's
    # connection pool, and the trace store's sqlite connections, which are
    # only closed when garbage-collected.
    try:
        from ollabridge.db.database import engine

        engine.dispose()
    except Exception:
        pass
    gc.collect()
    # Remove only the directory mkdtemp created for this session.
    if _TEST_HOME.name.startswith(_PREFIX) and _TEST_HOME.parent == Path(tempfile.gettempdir()):
        shutil.rmtree(_TEST_HOME, ignore_errors=True)
