from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True, frozen=True)
class RawPage:
    body: str
    capcodes: tuple[str, ...]
    protocol: str = "FLEX"
    page_type: str = "ALN"
    source_time: str | None = None
    mode: str | None = None
    frame: str | None = None
    decoder: str = "multimon"
    confidence: str | None = None
    received_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True, frozen=True)
class CapcodeInfo:
    capcode: str
    discipline: str | None = None
    region: str | None = None
    region_code: str | None = None
    location: str | None = None
    remark: str | None = None
    short: str | None = None


@dataclass(slots=True)
class P2000Message:
    body: str
    capcodes: list[str]
    received_at: datetime
    source_time: str | None = None
    protocol: str = "FLEX"
    page_type: str = "ALN"
    mode: str | None = None
    frame: str | None = None
    decoder: str = "multimon"
    confidence: str | None = None
    priority: int | None = None
    disciplines: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    region_codes: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remarks: list[str] = field(default_factory=list)
    shorts: list[str] = field(default_factory=list)
    capcode_details: list[CapcodeInfo] = field(default_factory=list)
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    @property
    def message_id(self) -> str:
        raw = "|".join([self.body, *sorted(self.capcodes)])
        return sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:20]

    @property
    def summary(self) -> str:
        text = " ".join(self.body.split())
        return text if len(text) <= 240 else text[:237] + "..."

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = self.message_id
        data["summary"] = self.summary
        data["event_type"] = "message"
        data["received_at"] = self.received_at.isoformat()
        return data
