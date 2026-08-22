from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import RawPage

_CAPCODE_RE = re.compile(r"^\d{1,9}$")


def normalize_capcode(value: str) -> str:
    value = value.strip().strip("[]")
    if not _CAPCODE_RE.fullmatch(value):
        raise ValueError(f"invalid capcode: {value!r}")
    return value.zfill(9)


def parse_multimon_line(line: str) -> RawPage | None:
    """Parse the stable pipe-delimited FLEX output used by P2000.

    Expected shape:
      FLEX|timestamp|mode|frame|capcode [capcode...]|ALN|message

    Extra pipes inside the message are preserved by maxsplit=6.
    Malformed/non-alpha lines are ignored instead of raising.
    """
    line = line.strip()
    if not line.startswith("FLEX|"):
        return None
    parts = line.split("|", 6)
    if len(parts) != 7:
        return None
    protocol, source_time, mode, frame, raw_capcodes, page_type, body = parts
    if page_type.strip().upper() not in {"ALN", "NUM"}:
        return None
    capcodes: list[str] = []
    for token in raw_capcodes.replace(",", " ").split():
        try:
            capcodes.append(normalize_capcode(token))
        except ValueError:
            continue
    if not capcodes or not body.strip():
        return None
    return RawPage(
        body=body.strip(),
        capcodes=tuple(dict.fromkeys(capcodes)),
        protocol=protocol.strip().upper(),
        page_type=page_type.strip().upper(),
        source_time=source_time.strip() or None,
        mode=mode.strip() or None,
        frame=frame.strip() or None,
        decoder="multimon",
    )


def parse_deflex_log_line(line: str) -> RawPage | None:
    """Parse the current deFLEX viewer log line.

    Current deFLEX FLEX logs use:
      <UTC ts> FLEX|<carrier>|<slot>|<tier>|0|ALN|<body>

    The 0 is not a real capcode, so the page is emitted with no capcodes. This is
    intentionally explicit: callers can publish the body, but must not fabricate
    P2000 enrichment.
    """
    line = line.strip()
    match = re.match(
        r"^(?P<ts>\S+)\s+FLEX\|(?P<carrier>\d+)\|(?P<slot>\d+)\|"
        r"(?P<tier>[A-D])\|0\|ALN\|(?P<body>.*)$",
        line,
    )
    if not match or not match.group("body").strip():
        return None
    try:
        received = datetime.fromisoformat(match.group("ts").replace("Z", "+00:00"))
    except ValueError:
        received = datetime.now(timezone.utc)
    return RawPage(
        body=match.group("body").replace("\\n", "\n").strip(),
        capcodes=(),
        source_time=match.group("ts"),
        mode=f"carrier:{match.group('carrier')}",
        frame=match.group("slot"),
        decoder="deflex",
        confidence=match.group("tier"),
        received_at=received,
    )
