"""Regression tests for websockets client API compatibility."""

from ollabridge.core.websocket_client import connection_options


def test_connection_options_for_legacy_client():
    def legacy_connect(uri, *, extra_headers=None, ping_interval=20, close_timeout=10):
        pass

    options = connection_options(
        legacy_connect,
        headers={"Authorization": "Bearer token"},
        ping_interval=25,
        close_timeout=5,
        proxy=None,
    )

    assert options == {
        "extra_headers": {"Authorization": "Bearer token"},
        "ping_interval": 25,
        "close_timeout": 5,
    }


def test_connection_options_for_current_client():
    def current_connect(
        uri,
        *,
        additional_headers=None,
        ping_interval=20,
        close_timeout=10,
        proxy=True,
    ):
        pass

    options = connection_options(
        current_connect,
        headers={"Authorization": "Bearer token"},
        ping_interval=25,
        close_timeout=5,
        proxy=None,
    )

    assert options == {
        "additional_headers": {"Authorization": "Bearer token"},
        "ping_interval": 25,
        "close_timeout": 5,
        "proxy": None,
    }
