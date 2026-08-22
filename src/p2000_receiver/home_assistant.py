from __future__ import annotations

from typing import Any

from .config import RouteConfig
from .models import CapcodeInfo, P2000Message


def sensor_state(message: P2000Message, max_length: int = 200) -> str:
    """Return a compact Home Assistant state that always stays below 255 chars."""
    if max_length < 4:
        raise ValueError("max_length must be at least 4")
    text = " ".join(message.body.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _capcode_detail(detail: CapcodeInfo) -> str:
    metadata = [detail.discipline, detail.location, detail.remark]
    suffix = " · ".join(value for value in metadata if value)
    return f"{detail.capcode} — {suffix}" if suffix else detail.capcode


def history_entry(message: P2000Message) -> dict[str, Any]:
    """Compact representation used by the retained per-route 10-message history."""
    entry: dict[str, Any] = {
        "id": message.message_id,
        "time": message.source_time or message.received_at.isoformat(),
        "message": message.body,
    }
    optional = {
        "priority": message.priority,
        "service": ", ".join(message.services),
        "discipline": ", ".join(message.disciplines),
        "capcodes": message.capcodes,
        "location": ", ".join(message.locations),
        "region": ", ".join(message.regions),
    }
    entry.update({k: v for k, v in optional.items() if v not in (None, "", [])})
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
    attributes: dict[str, Any] = {
        "message": message.body,
        "time": message.source_time or message.received_at.isoformat(),
        "received_at": message.received_at.isoformat(),
        "message_id": message.message_id,
        "route": route.name,
        "route_id": route.id,
        "decoder": message.decoder,
    }
    optional = {
        "priority": message.priority,
        "service": ", ".join(message.services),
        "services": message.services,
        "discipline": ", ".join(message.disciplines),
        "region": ", ".join(message.regions),
        "location": ", ".join(message.locations),
        "remark": ", ".join(message.remarks),
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
