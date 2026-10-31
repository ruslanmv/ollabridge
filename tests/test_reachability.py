"""Change-only logging for an unreachable Ollama, and the logging setup that
gives every line a timestamp.

Observed 2026-10-15: an idle gateway printed ``local runtime /api/tags
failed: All connection attempts failed`` once a minute for hours, plus
``Could not list Ollama models at ...`` on every dashboard poll, all without
timestamps. The policy pinned here: first failure WARNING with a hint,
repeats DEBUG, a reminder every N minutes, recovery INFO, and one state
shared by every caller.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager

import httpx
import pytest

from ollabridge.core import logsetup
from ollabridge.core.reachability import EndpointMonitor

URL = "http://localhost:11434"


class Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def monitor(caplog):
    clock = Clock()
    logger = logging.getLogger("test.reachability")
    mon = EndpointMonitor(
        "Ollama",
        hint="Start Ollama.",
        reminder_s=600,
        clock=clock,
        wall=lambda: 1_700_000_000.0 + clock.now,
        logger=logger,
    )
    caplog.set_level(logging.DEBUG, logger="test.reachability")
    return mon, clock, caplog


def _levels(caplog) -> list[str]:
    return [r.levelname for r in caplog.records]


def test_first_failure_warns_once_with_address_and_hint(monitor):
    mon, _clock, caplog = monitor
    err = httpx.ConnectError("All connection attempts failed")
    mon.failure(URL, err)
    mon.failure(URL, err)
    mon.failure(URL, err)

    assert _levels(caplog) == ["WARNING", "DEBUG", "DEBUG"]
    first = caplog.records[0].getMessage()
    assert URL in first and "ConnectError" in first and "Start Ollama." in first
    assert "logged at DEBUG" in first
    snap = mon.snapshot(URL)
    assert snap["reachable"] is False
    assert snap["consecutive_failures"] == 3
    assert snap["last_error"].startswith("ConnectError")
    assert snap["since"].startswith("2023-")  # ISO timestamp of the transition


def test_reminder_fires_once_per_interval_with_duration_and_attempts(monitor):
    mon, clock, caplog = monitor
    mon.failure(URL, "refused")
    for _ in range(9):
        clock.advance(60)
        mon.failure(URL, "refused")
    assert _levels(caplog).count("WARNING") == 1  # 9 minutes: no reminder yet

    clock.advance(60)  # minute 10
    mon.failure(URL, "refused")
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "still not reachable" in warnings[1]
    assert "10 min" in warnings[1] and "11 attempts" in warnings[1]

    clock.advance(60)
    mon.failure(URL, "refused")
    assert _levels(caplog).count("WARNING") == 2  # back to DEBUG until the next interval


def test_recovery_is_logged_once_with_outage_length(monitor):
    mon, clock, caplog = monitor
    mon.failure(URL, "refused")
    clock.advance(125 * 60)
    mon.success(URL)
    mon.success(URL)

    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 1
    assert "reachable again" in infos[0] and "2 h 05 min" in infos[0]
    snap = mon.snapshot(URL)
    assert snap["reachable"] is True and snap["consecutive_failures"] == 0
    assert snap["last_error"] is None


def test_first_success_is_quiet_and_trailing_slash_is_the_same_endpoint(monitor):
    mon, _clock, caplog = monitor
    mon.success(URL + "/")
    assert _levels(caplog) == ["DEBUG"]
    assert mon.is_reachable(URL) is True
    mon.failure(URL, "refused")
    assert mon.snapshot(URL + "/")["reachable"] is False
    assert mon.snapshot("http://other:11434") == {
        "url": "http://other:11434",
        "reachable": None,
        "since": None,
        "consecutive_failures": 0,
        "last_error": None,
    }


def test_outage_then_recovery_then_new_outage_warns_again(monitor):
    mon, clock, caplog = monitor
    mon.failure(URL, "refused")
    clock.advance(30)
    mon.success(URL)
    clock.advance(30)
    mon.failure(URL, "refused")
    assert _levels(caplog) == ["WARNING", "INFO", "WARNING"]


# --- every Ollama caller shares one state ---------------------------------------


def test_catalog_client_and_ollama_client_report_one_outage(monkeypatch, caplog):
    """The two emitters from the observed log now produce a single WARNING."""
    import asyncio

    from ollabridge.addons.local_catalog.client import (
        LocalRuntimeClient,
        LocalRuntimeUnreachable,
    )
    from ollabridge.core import runtime_settings as rts
    from ollabridge.providers import ollama_client

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("All connection attempts failed", request=request)

    transport = httpx.MockTransport(refuse)
    monkeypatch.setattr(rts, "ollama_base_url", lambda: URL)
    monkeypatch.setattr(
        ollama_client, "_client",
        lambda timeout: httpx.AsyncClient(timeout=timeout, transport=transport),
    )
    catalog = LocalRuntimeClient(base_url=URL)
    monkeypatch.setattr(
        catalog, "_http",
        lambda timeout=None: httpx.AsyncClient(base_url=URL, transport=transport),
    )

    with caplog.at_level(logging.DEBUG, logger="ollabridge"):
        with pytest.raises(LocalRuntimeUnreachable) as excinfo:
            asyncio.run(catalog.list_tags())
        assert asyncio.run(ollama_client.list_models()) == []
        assert asyncio.run(ollama_client.list_models()) == []
        assert asyncio.run(catalog.ping()) is False

    assert URL in str(excinfo.value) and "ConnectError" in str(excinfo.value)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert URL in warnings[0].getMessage()
    assert "api/tags failed" not in caplog.text
    assert "Could not list Ollama models" not in caplog.text
    debug_repeats = [r for r in caplog.records if r.levelno == logging.DEBUG and "still not reachable" in r.getMessage()]
    assert len(debug_repeats) == 3


# --- logging setup -----------------------------------------------------------------


@contextmanager
def _bare_root_logger():
    """Run with no root handlers at all. pytest adds its own capture
    handlers around each test phase, so the removal happens inside the test
    body and everything is put back afterwards."""
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_noisy = {name: logging.getLogger(name).level for name in logsetup.NOISY_LOGGERS}
    for h in saved_handlers:
        root.removeHandler(h)
    try:
        yield root
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
        for name, lvl in saved_noisy.items():
            logging.getLogger(name).setLevel(lvl)


def test_configure_logging_is_idempotent_and_timestamps_lines():
    with _bare_root_logger() as root:
        first = logsetup.configure_logging("debug")
        second = logsetup.configure_logging("warning")
        assert first is second
        assert [h.get_name() for h in root.handlers] == [logsetup.HANDLER_NAME]
        assert root.level == logging.WARNING
        fmt = first.formatter
        assert fmt is not None
        line = fmt.format(
            logging.LogRecord("ollabridge.reachability", logging.WARNING, __file__, 1, "Ollama down", (), None)
        )
        # Timestamped (ISO in plain mode, clock time in pretty mode), with the
        # level and the component the logger maps to.
        assert re.match(r"^(\d{4}-\d\d-\d\dT)?\d\d:\d\d:\d\d\.\d{3}", line)
        assert "WARN" in line and "runtime" in line and "Ollama down" in line


def test_noisy_http_loggers_never_go_below_warning():
    with _bare_root_logger():
        logsetup.configure_logging("debug")
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
        logsetup.configure_logging("error")
        assert logging.getLogger("httpx").level == logging.ERROR


def test_ensure_only_configures_when_nothing_has(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    with _bare_root_logger() as root:
        assert logsetup.ensure_logging_configured() is True
        assert root.level == logging.DEBUG
        assert logsetup.ensure_logging_configured() is False  # already configured: untouched
    assert logsetup.level_from_name("trace") == logging.DEBUG
    assert logsetup.level_from_name("nonsense") == logging.INFO
