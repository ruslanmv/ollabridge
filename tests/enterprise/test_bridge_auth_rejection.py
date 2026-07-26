"""The cloud bridge must stop reconnecting when the device token is rejected.

Regression: when OllaBridge Cloud unlinks/revokes a device it closes the relay
WebSocket with code 4401. The bridge used to treat that like any transient
error and reconnect forever, spamming:
    Cloud bridge error: received 4401 (private use) Invalid token
Now a 4401/4403 close is recognised as a permanent auth rejection so the loop
stops with an actionable status.
"""

from __future__ import annotations

from types import SimpleNamespace

from ollabridge.cloud.bridge_manager import (
    AUTH_REJECTION_CODES,
    _is_auth_rejection,
)


class _CloseFrame:
    def __init__(self, code):
        self.code = code


def test_detects_code_on_rcvd_frame():
    exc = SimpleNamespace(rcvd=_CloseFrame(4401), sent=None)
    assert _is_auth_rejection(exc) is True


def test_detects_code_on_sent_frame():
    exc = SimpleNamespace(rcvd=None, sent=_CloseFrame(4403))
    assert _is_auth_rejection(exc) is True


def test_detects_direct_code_attribute():
    exc = SimpleNamespace(code=4401)
    assert _is_auth_rejection(exc) is True


def test_detects_code_in_message_text():
    # Older/other websockets versions surface only the string form.
    exc = Exception("received 4401 (private use) Invalid token; then sent 4401")
    assert _is_auth_rejection(exc) is True


def test_transient_errors_are_not_auth_rejections():
    assert _is_auth_rejection(Exception("connection reset by peer")) is False
    assert _is_auth_rejection(SimpleNamespace(rcvd=_CloseFrame(1006), sent=None)) is False
    assert _is_auth_rejection(TimeoutError("handshake timed out")) is False


def test_expected_codes():
    assert AUTH_REJECTION_CODES == frozenset({4401, 4403})
