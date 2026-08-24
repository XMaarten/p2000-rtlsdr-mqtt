from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import RouteConfig
from .models import CapcodeInfo, P2000Message

_LOCAL_TZ = ZoneInfo("Europe/Amsterdam")


def sensor_state(message: P2000Message, max_length: int = 200) -> str:
    """Return a compact Home Assistant state that always stays below 255 chars."""
    if max_length < 4:
        raise ValueError("max_length must be at least 4")
    text = " ".join(message.body.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _source_time_utc(message: P2000Message) -> datetime:
    """Return the decoder timestamp as UTC, falling back to receive time.

    multimon-ng emits the FLEX timestamp without a timezone marker. In practice
    that timestamp is UTC. Keep all internal storage in UTC and only localise it
    for human-facing Home Assistant attributes.
    """
    if message.source_time:
        raw = message.source_time.strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    received = message.received_at
    if received.tzinfo is None:
        received = received.replace(tzinfo=UTC)
    return received.astimezone(UTC)


def local_event_time(message: P2000Message) -> str:
    """Human-readable event time in Europe/Amsterdam, including DST."""
    return _source_time_utc(message).astimezone(_LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _unit_detail(detail: CapcodeInfo) -> str | None:
    metadata = [
        detail.service or detail.discipline,
        detail.station or detail.location,
        detail.callsign,
        detail.unit_type_name or detail.unit_type,
        detail.description or detail.remark,
    ]
    values = list(dict.fromkeys(value for value in metadata if value))
    return " · ".join(values) if values else None


def _capcode_detail(detail: CapcodeInfo) -> str:
    unit = _unit_detail(detail)
    return f"{detail.capcode} — {unit}" if unit else detail.capcode


def _unit_details(message: P2000Message) -> list[str]:
    return list(
        dict.fromkeys(
            unit
            for detail in message.capcode_details
            if (unit := _unit_detail(detail)) is not None
        )
    )


def history_entry(message: P2000Message) -> dict[str, Any]:
    """Compact representation used by the retained per-route 10-message history."""
    entry: dict[str, Any] = {
        "id": message.message_id,
        "time": local_event_time(message),
        "message": message.body,
    }
    if message.source_time:
        entry["source_time"] = message.source_time
    optional = {
        "priority": message.priority,
        "service": ", ".join(message.services),
        "discipline": ", ".join(message.disciplines),
        "capcodes": message.capcodes,
        "capcode_details": [_capcode_detail(detail) for detail in message.capcode_details],
        "units": _unit_details(message),
        "location": ", ".join(message.locations),
        "station": ", ".join(message.stations),
        "callsign": ", ".join(message.callsigns),
        "unit_type": ", ".join(message.unit_type_names or message.unit_types),
        "unit_number": ", ".join(message.unit_numbers),
        "region": ", ".join(message.regions),
    }
    entry.update({key: value for key, value in optional.items() if value not in (None, "", [])})
    return entry


def history_attributes(route: RouteConfig, messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "route": route.name,
        "route_id": route.id,
        "count": len(messages),
        "messages": messages,
    }


def sensor_attributes(route: RouteConfig, message: P2000Message) -> dict[str, Any]:
    """Return human-readable attributes and omit empty optional values."""
    source_utc = _source_time_utc(message)
    attributes: dict[str, Any] = {
        "message": message.body,
        "time": local_event_time(message),
        "event_time_utc": source_utc.isoformat(),
        "received_at": message.received_at.isoformat(),
        "message_id": message.message_id,
        "route": route.name,
        "route_id": route.id,
        "decoder": message.decoder,
    }
    if message.source_time:
        attributes["source_time"] = message.source_time
    optional = {
        "priority": message.priority,
        "service": ", ".join(message.services),
        "services": message.services,
        "discipline": ", ".join(message.disciplines),
        "region": ", ".join(message.regions),
        "location": ", ".join(message.locations),
        "station": ", ".join(message.stations),
        "description": ", ".join(message.descriptions),
        "remark": ", ".join(message.remarks),
        "unit_type": ", ".join(message.unit_types),
        "unit_type_name": ", ".join(message.unit_type_names),
        "callsign": ", ".join(message.callsigns),
        "unit_number": ", ".join(message.unit_numbers),
        "units": _unit_details(message),
        "capcodes": message.capcodes,
        "capcodes_text": ", ".join(message.capcodes),
        "capcode_details": [_capcode_detail(detail) for detail in message.capcode_details],
        "postal_code": message.postal_code,
        "latitude": message.latitude,
        "longitude": message.longitude,
        "confidence": message.confidence,
    }
    attributes.update(
        {key: value for key, value in optional.items() if value not in (None, "", [])}
    )
    return attributes
