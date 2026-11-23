"""Claude Code telemetry → usage events.

Claude Code exports OpenTelemetry logs ("events"). Each ``api_request`` event
describes one API request with its token counts and the tool's own cost
estimate. This module parses the OTLP **http/json** encoding of those logs —
plain JSON, so no protobuf dependency and no collector process.

Only ``api_request`` events are read, and only their numeric usage fields plus
model and session identifiers. Prompt text is never read, even when the user
has enabled prompt logging on the Claude Code side.

Attribute names follow the Claude Code monitoring documentation
(https://code.claude.com/docs/en/monitoring-usage). The parser is tolerant of
missing attributes: anything absent stays unknown.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any, Dict, Iterator, List, Mapping, Optional

from .contract import Usage, UsageEvent, clean_label
from .normalize import usd_to_micro

_EVENT_SUFFIX = "api_request"


def _value(any_value: Any) -> Any:
    """Unwrap an OTLP ``AnyValue`` (``{"stringValue": ...}`` etc.)."""
    if not isinstance(any_value, Mapping):
        return any_value
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in any_value:
            value = any_value[key]
            if key == "intValue":  # JSON encodes int64 as a string
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
            return value
    return None


def _attributes(items: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for item in items or ():
        if isinstance(item, Mapping) and isinstance(item.get("key"), str):
            out[item["key"]] = _value(item.get("value"))
    return out


def _int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _timestamp(record: Mapping[str, Any], attrs: Mapping[str, Any]) -> dt.datetime:
    iso = attrs.get("event.timestamp")
    if isinstance(iso, str):
        try:
            return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            pass
    for key in ("timeUnixNano", "observedTimeUnixNano"):
        nanos = _int(record.get(key))
        if nanos:
            return dt.datetime.fromtimestamp(nanos / 1e9, tz=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def _records(payload: Mapping[str, Any]) -> Iterator[tuple[Dict[str, Any], Mapping[str, Any]]]:
    for resource_logs in payload.get("resourceLogs") or ():
        resource = _attributes((resource_logs.get("resource") or {}).get("attributes"))
        for scope_logs in resource_logs.get("scopeLogs") or ():
            for record in scope_logs.get("logRecords") or ():
                if isinstance(record, Mapping):
                    yield {**resource, **_attributes(record.get("attributes"))}, record


def _is_api_request(attrs: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
    names = (attrs.get("event.name"), _value(record.get("body")), record.get("eventName"))
    return any(isinstance(n, str) and n.endswith(_EVENT_SUFFIX) for n in names)


def parse_logs(payload: Mapping[str, Any], *, billing_mode: str = "subscription") -> List[UsageEvent]:
    """Usage events for every ``api_request`` record in an OTLP logs export."""
    events: List[UsageEvent] = []
    for attrs, record in _records(payload):
        if not _is_api_request(attrs, record):
            continue
        occurred_at = _timestamp(record, attrs)
        session = str(attrs.get("session.id") or "")

        # Deterministic id, so a re-exported batch is recognised as a duplicate.
        identity = attrs.get("request_id") or "|".join(
            str(part) for part in (
                session, attrs.get("event.sequence"), occurred_at.isoformat(), attrs.get("model"),
                attrs.get("input_tokens"), attrs.get("output_tokens"),
            )
        )
        event_id = "cc_" + hashlib.sha256(str(identity).encode()).hexdigest()[:40]

        # Claude Code's input_tokens already excludes cache reads and writes.
        usage = Usage(
            input_tokens=_int(attrs.get("input_tokens")),
            cache_read_tokens=_int(attrs.get("cache_read_tokens")),
            cache_write_tokens=_int(attrs.get("cache_creation_tokens")),
            output_tokens=_int(attrs.get("output_tokens")),
        )
        micros = _int(attrs.get("cost_usd_micros"))
        estimated = micros if micros is not None else usd_to_micro(attrs.get("cost_usd"))

        event = UsageEvent(
            event_id=event_id,
            trace_id=("cc-" + "".join(c for c in session if c.isalnum() or c in "._:-"))[:128]
            if session else None,
            occurred_at=occurred_at,
            source="claude_code_otel",
            application_id="claude-code",
            agent_id=clean_label(attrs.get("agent.name")) or "claude-code",
            provider="anthropic",
            model=clean_label(attrs.get("model")),
            execution="provider_api",
            billing_mode=billing_mode,
            usage=usage,
            measurement="locally_observed" if usage.known else "unavailable",
            latency_ms=_int(attrs.get("duration_ms")),
        )
        # The tool's figure is an estimate, not a charge stated by the biller.
        event.cost.estimated_micro = estimated
        if estimated is not None:
            event.cost.pricing_version = "claude-code-reported"
        events.append(event)
    return events
