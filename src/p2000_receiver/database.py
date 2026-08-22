from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import sqlite3
import urllib.request
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import CapcodeInfo
from .parsers import normalize_capcode

_LOG = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS capcodes (
    capcode TEXT PRIMARY KEY,
    discipline TEXT,
    region TEXT,
    region_code TEXT,
    location TEXT,
    remark TEXT,
    short TEXT
);
CREATE INDEX IF NOT EXISTS idx_capcodes_region ON capcodes(region);
CREATE INDEX IF NOT EXISTS idx_capcodes_discipline ON capcodes(discipline);
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geocode_cache (
    query TEXT PRIMARY KEY,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS route_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_route_history_route_id
    ON route_history(route_id, id DESC);
"""


class CapcodeDatabase:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=20)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def lookup_many(self, capcodes: list[str]) -> list[CapcodeInfo]:
        if not capcodes:
            return []
        marks = ",".join("?" for _ in capcodes)
        rows = self.conn.execute(
            f"SELECT * FROM capcodes WHERE capcode IN ({marks})", capcodes
        ).fetchall()
        by_code = {row["capcode"]: row for row in rows}
        out: list[CapcodeInfo] = []
        for code in capcodes:
            row = by_code.get(code)
            if row:
                out.append(
                    CapcodeInfo(
                        capcode=code,
                        discipline=row["discipline"],
                        region=row["region"],
                        region_code=row["region_code"],
                        location=row["location"],
                        remark=row["remark"],
                        short=row["short"],
                    )
                )
            else:
                out.append(CapcodeInfo(capcode=code))
        return out

    def metadata(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def record_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM capcodes").fetchone()
        return int(row[0])

    def needs_update(self, interval_hours: int) -> bool:
        value = self.metadata("capcodes_updated_at")
        if not value:
            return True
        try:
            last = datetime.fromisoformat(value)
        except ValueError:
            return True
        return datetime.now(UTC) - last >= timedelta(hours=interval_hours)

    def geocode_get(self, query: str) -> tuple[float, float] | None:
        row = self.conn.execute(
            "SELECT latitude, longitude FROM geocode_cache WHERE query=?", (query,)
        ).fetchone()
        return (float(row[0]), float(row[1])) if row else None

    def geocode_put(self, query: str, latitude: float, longitude: float) -> None:
        self.conn.execute(
            "INSERT INTO geocode_cache(query, latitude, longitude, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(query) DO UPDATE SET latitude=excluded.latitude, "
            "longitude=excluded.longitude, updated_at=excluded.updated_at",
            (query, latitude, longitude, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def history_add(
        self,
        route_id: str,
        message_id: str,
        received_at: str,
        payload: dict,
        limit: int = 10,
    ) -> list[dict]:
        if limit < 1:
            raise ValueError("history limit must be at least 1")
        with self.conn:
            self.conn.execute(
                "INSERT INTO route_history(route_id,message_id,received_at,payload) "
                "VALUES(?,?,?,?)",
                (route_id, message_id, received_at, json.dumps(payload, ensure_ascii=False)),
            )
            self.conn.execute(
                "DELETE FROM route_history WHERE route_id=? AND id NOT IN "
                "(SELECT id FROM route_history WHERE route_id=? ORDER BY id DESC LIMIT ?)",
                (route_id, route_id, limit),
            )
        return self.history_get(route_id, limit)

    def history_get(self, route_id: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM route_history WHERE route_id=? ORDER BY id DESC LIMIT ?",
            (route_id, limit),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update_from_url(self, url: str, min_records: int = 5000, timeout: int = 30) -> int:
        request = urllib.request.Request(url, headers={"User-Agent": "p2000-rtlsdr-mqtt/0.1"})
        with closing(urllib.request.urlopen(request, timeout=timeout)) as response:  # noqa: S310
            payload = response.read()
        return self.update_from_csv_bytes(payload, source=url, min_records=min_records)

    def update_from_csv_bytes(self, payload: bytes, source: str, min_records: int = 5000) -> int:
        text = _decode_csv(payload)
        records = list(_parse_capcode_csv(text))
        if len(records) < min_records:
            raise ValueError(
                f"capcode update rejected: only {len(records)} records (minimum {min_records})"
            )
        digest = hashlib.sha256(payload).hexdigest()
        if digest == self.metadata("capcodes_source_sha256"):
            _LOG.info("Capcode database unchanged (%s records)", len(records))
            return len(records)

        now = datetime.now(UTC).isoformat()
        with self.conn:
            self.conn.execute("DROP TABLE IF EXISTS capcodes_staging")
            # CREATE TABLE ... AS SELECT does not copy PRIMARY KEY/UNIQUE constraints.
            # The Bommel dataset can contain duplicate capcodes, so staging needs its
            # own primary key to make the upsert deterministic and prevent the final
            # INSERT into capcodes from failing with UNIQUE constraint errors.
            self.conn.execute(
                "CREATE TEMP TABLE capcodes_staging ("
                "capcode TEXT PRIMARY KEY,"
                "discipline TEXT,"
                "region TEXT,"
                "region_code TEXT,"
                "location TEXT,"
                "remark TEXT,"
                "short TEXT"
                ")"
            )
            self.conn.executemany(
                "INSERT INTO capcodes_staging "
                "(capcode,discipline,region,region_code,location,remark,short) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(capcode) DO UPDATE SET "
                "discipline=excluded.discipline, "
                "region=excluded.region, "
                "region_code=excluded.region_code, "
                "location=excluded.location, "
                "remark=excluded.remark, "
                "short=excluded.short",
                records,
            )
            count = self.conn.execute("SELECT COUNT(*) FROM capcodes_staging").fetchone()[0]
            duplicate_count = len(records) - count
            if duplicate_count:
                _LOG.warning(
                    "Capcode source contained %s duplicate row(s); kept one row per capcode",
                    duplicate_count,
                )
            if count < min_records:
                raise ValueError(f"staging validation failed: {count} records")
            self.conn.execute("DELETE FROM capcodes")
            self.conn.execute("INSERT INTO capcodes SELECT * FROM capcodes_staging")
            self.conn.executemany(
                "INSERT INTO metadata(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [
                    ("capcodes_source", source),
                    ("capcodes_source_sha256", digest),
                    ("capcodes_updated_at", now),
                    ("capcodes_record_count", str(count)),
                ],
            )
        _LOG.info("Updated capcode database: %s records", count)
        return int(count)


def _decode_csv(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _parse_capcode_csv(text: str):
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return

    first = [c.strip().lower() for c in rows[0]]
    aliases = {
        "capcode": {"capcode", "code", "address"},
        "discipline": {"discipline", "dienst"},
        "region": {"regio", "region"},
        "region_code": {"regiocode", "regioncode", "regio code"},
        "location": {"korps", "location", "plaats"},
        "remark": {"omschrijving", "remark", "description"},
        "short": {"short", "kort", "korte omschrijving"},
    }
    index: dict[str, int] = {}
    for key, names in aliases.items():
        for i, header in enumerate(first):
            if header in names:
                index[key] = i
                break
    has_header = "capcode" in index
    data_rows = rows[1:] if has_header else rows

    def col(row: list[str], key: str, fallback: int) -> str | None:
        i = index.get(key, fallback)
        return row[i] if i < len(row) else None

    for row in data_rows:
        if not row or all(not c.strip() for c in row):
            continue
        try:
            code = normalize_capcode(col(row, "capcode", 0) or "")
        except ValueError:
            continue
        yield (
            code,
            _clean(col(row, "discipline", 1)),
            _clean(col(row, "region", 2)),
            _clean(col(row, "region_code", 3)),
            _clean(col(row, "location", 4)),
            _clean(col(row, "remark", 5)),
            _clean(col(row, "short", 6)),
        )
