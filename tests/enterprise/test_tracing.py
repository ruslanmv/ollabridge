"""Trace store: metadata-only persistence, retrieval, and safe defaults."""

from __future__ import annotations

import sqlite3

from ollabridge.tracing.store import TraceRecord, TraceStore


def _store(tmp_path):
    return TraceStore(tmp_path / "traces.db")


def test_record_and_get(tmp_path):
    store = _store(tmp_path)
    rec = TraceRecord(
        requested_model="coding",
        resolved_model="qwen2.5-coder:14b",
        provider=None,
        device="local",
        latency_ms=420,
        tokens_in=12,
        tokens_out=40,
    )
    store.record(rec)
    got = store.get(rec.request_id)
    assert got is not None
    assert got.resolved_model == "qwen2.5-coder:14b"
    assert got.cloud_relay is False
    assert got.prompt_logging is False
    assert got.ok is True


def test_list_orders_newest_first(tmp_path):
    store = _store(tmp_path)
    first = TraceRecord(ts="2026-01-01T00:00:00Z", requested_model="a")
    second = TraceRecord(ts="2026-01-02T00:00:00Z", requested_model="b")
    store.record(first)
    store.record(second)
    listed = store.list(limit=10)
    assert [t.requested_model for t in listed] == ["b", "a"]


def test_schema_has_no_content_columns(tmp_path):
    """The traces table must be structurally unable to hold prompt content."""
    store = _store(tmp_path)
    store.record(TraceRecord())
    cols = {
        row[1]
        for row in sqlite3.connect(store.path).execute("PRAGMA table_info(traces)")
    }
    # Exactly the TraceRecord metadata fields — nothing that could carry content.
    assert cols == set(TraceRecord.model_fields)
    for forbidden in (
        "prompt_text",
        "messages",
        "content",
        "response_text",
        "completion_text",
        "prompt",
        "response",
    ):
        assert forbidden not in cols


def test_prune_keeps_newest(tmp_path):
    store = _store(tmp_path)
    for i in range(10):
        store.record(TraceRecord(ts=f"2026-01-{i+1:02d}T00:00:00Z"))
    removed = store.prune(keep=3)
    assert removed == 7
    assert len(store.list(limit=100)) == 3


def test_request_id_shape():
    rec = TraceRecord()
    assert rec.request_id.startswith("req_")
    assert len(rec.request_id) > 20
