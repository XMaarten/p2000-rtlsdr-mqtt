from __future__ import annotations

import re

from .database import CapcodeDatabase
from .models import CapcodeInfo, P2000Message, RawPage

_POSTCODE_RE = re.compile(r"\b([1-9][0-9]{3})\s?([A-Z]{2})\b", re.IGNORECASE)
_PRIORITY_PATTERNS = [
    (1, re.compile(r"^(?:A\s?1|P\s?1|PRIO\s?1)\b", re.IGNORECASE)),
    (2, re.compile(r"^(?:A\s?2|P\s?2|PRIO\s?2)\b", re.IGNORECASE)),
    (3, re.compile(r"^(?:B\s?[123]|P\s?3|PRIO\s?3)\b", re.IGNORECASE)),
    (4, re.compile(r"^(?:P\s?4|PRIO\s?4)\b", re.IGNORECASE)),
]


def _unique(values):
    return list(dict.fromkeys(v for v in values if v))


def detect_priority(body: str) -> int | None:
    compact = " ".join(body.split())
    for priority, pattern in _PRIORITY_PATTERNS:
        if pattern.search(compact):
            return priority
    return None


def detect_services(body: str, details: list[CapcodeInfo]) -> list[str]:
    """Return stable, human-readable emergency service categories."""
    services: list[str] = []

    def add(name: str) -> None:
        if name and name not in services:
            services.append(name)

    # p2000-capcodes has an explicit normalized service field. Prefer it.
    for detail in details:
        if detail.service:
            add(detail.service)

    metadata = " ".join(
        value
        for detail in details
        for value in (
            detail.discipline,
            detail.service,
            detail.region_code,
            detail.description,
            detail.remark,
            detail.short,
            detail.unit_type,
            detail.unit_type_name,
            detail.callsign,
        )
        if value
    ).casefold()
    body_cf = " ".join(body.split()).casefold()

    if "brandweer" in metadata or "brw" in metadata or re.search(r"\bbr\b", body_cf):
        add("Brandweer")
    if (
        any(
            term in metadata
            for term in ("ambulance", "ambulancezorg", "mka", "ambu", "lifeliner", "traumaheli")
        )
        or re.match(r"^(?:a\s?[012]|b\s?[12])\b", body_cf)
    ):
        add("Ambulance")
    if "politie" in metadata or "politie" in body_cf:
        add("Politie")
    if "ghor" in metadata or "ghor" in body_cf:
        add("GHOR")
    if "knrm" in metadata or "knrm" in body_cf:
        add("KNRM")

    if not services:
        for detail in details:
            if detail.discipline:
                add(detail.discipline)
    return services


def enrich(page: RawPage, db: CapcodeDatabase) -> P2000Message:
    details = db.lookup_many(list(page.capcodes))
    postcode_match = _POSTCODE_RE.search(page.body.upper())
    descriptions = _unique(d.description for d in details)
    source_remarks = _unique(d.remark for d in details)
    # Existing route `remark` filters historically matched source descriptions.
    # Include both the new description and source remark fields to remain compatible.
    filter_remarks = _unique([*descriptions, *source_remarks])
    return P2000Message(
        body=page.body,
        capcodes=list(page.capcodes),
        received_at=page.received_at,
        source_time=page.source_time,
        protocol=page.protocol,
        page_type=page.page_type,
        mode=page.mode,
        frame=page.frame,
        decoder=page.decoder,
        confidence=page.confidence,
        priority=detect_priority(page.body),
        disciplines=_unique(d.discipline for d in details),
        services=detect_services(page.body, details),
        regions=_unique(d.region for d in details),
        region_codes=_unique(d.region_code for d in details),
        locations=_unique(d.location for d in details),
        stations=_unique(d.station for d in details),
        descriptions=descriptions,
        remarks=filter_remarks,
        shorts=_unique(d.short for d in details),
        unit_types=_unique(d.unit_type for d in details),
        unit_type_names=_unique(d.unit_type_name for d in details),
        callsigns=_unique(d.callsign for d in details),
        unit_numbers=_unique(d.unit_number for d in details),
        capcode_details=details,
        postal_code=(
            f"{postcode_match.group(1)}{postcode_match.group(2).upper()}"
            if postcode_match
            else None
        ),
    )
