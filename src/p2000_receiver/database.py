from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import urllib.request
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import CapcodeInfo

_LOG = logging.getLogger(__name__)
_SQLITE_MAGIC = b"SQLite format 3\x00"

_RUNTIME_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
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

_REQUIRED_SOURCE_TABLES = {"capcodes", "capcodes_meta", "abbreviations"}
_REQUIRED_CAPCODE_COLUMNS = {
    "capcode",
    "discipline",
    "region",
    "location",
    "description",
    "remark",
}
_REQUIRED_META_COLUMNS = {
    "capcode",
    "service",
    "region_code",
    "station",
    "unit_type",
    "unit_type_name",
    "callsign",
    "unit_number",
    "status",
    "confidence",
}


class RuntimeDatabase:
    """Writable local state that must survive capcode dataset replacements."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=20)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_RUNTIME_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def metadata(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def metadata_set_many(self, values: dict[str, str]) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT INTO metadata(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                list(values.items()),
            )

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


class CapcodeDatabase:
    """Read-only reference dataset plus separate writable runtime state.

    `capcodes_path` is a replaceable artifact downloaded from p2000-capcodes.
    `runtime_path` contains only local history, geocode cache and updater metadata.
    """

    def __init__(self, capcodes_path: str | Path, runtime_path: str | Path):
        self.capcodes_path = Path(capcodes_path)
        self.capcodes_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime = RuntimeDatabase(runtime_path)

    def close(self) -> None:
        self.runtime.close()

    def _connect_reference(self) -> sqlite3.Connection:
        if not self.capcodes_path.exists():
            raise FileNotFoundError(f"capcode database not found: {self.capcodes_path}")
        conn = sqlite3.connect(
            f"file:{self.capcodes_path}?mode=ro",
            uri=True,
            timeout=10,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def lookup_many(self, capcodes: list[str]) -> list[CapcodeInfo]:
        if not capcodes:
            return []
        if not self.capcodes_path.exists():
            return [CapcodeInfo(capcode=code) for code in capcodes]

        marks = ",".join("?" for _ in capcodes)
        query = f"""
            SELECT
                c.capcode,
                c.discipline,
                m.service,
                c.region,
                m.region_code,
                c.location,
                m.station,
                c.description,
                c.remark,
                m.unit_type,
                m.unit_type_name,
                m.callsign,
                m.unit_number,
                m.status,
                m.confidence
            FROM capcodes AS c
            LEFT JOIN capcodes_meta AS m ON m.capcode = c.capcode
            WHERE c.capcode IN ({marks})
        """
        with closing(self._connect_reference()) as conn:
            rows = conn.execute(query, capcodes).fetchall()

        by_code = {row["capcode"]: row for row in rows}
        out: list[CapcodeInfo] = []
        for code in capcodes:
            row = by_code.get(code)
            if not row:
                out.append(CapcodeInfo(capcode=code))
                continue
            out.append(
                CapcodeInfo(
                    capcode=code,
                    discipline=_clean(row["discipline"]),
                    service=_clean(row["service"]),
                    region=_clean(row["region"]),
                    region_code=_clean(row["region_code"]),
                    location=_clean(row["location"]),
                    station=_clean(row["station"]),
                    description=_clean(row["description"]),
                    remark=_clean(row["remark"]),
                    short=_clean(row["callsign"]),
                    unit_type=_clean(row["unit_type"]),
                    unit_type_name=_clean(row["unit_type_name"]),
                    callsign=_clean(row["callsign"]),
                    unit_number=_clean(row["unit_number"]),
                    status=_clean(row["status"]),
                    metadata_confidence=_clean(row["confidence"]),
                )
            )
        return out

    def metadata(self, key: str) -> str | None:
        return self.runtime.metadata(key)

    def record_count(self) -> int:
        if not self.capcodes_path.exists():
            return 0
        try:
            with closing(self._connect_reference()) as conn:
                row = conn.execute("SELECT COUNT(*) FROM capcodes").fetchone()
            return int(row[0])
        except (sqlite3.DatabaseError, OSError):
            return 0

    def abbreviation_count(self) -> int:
        if not self.capcodes_path.exists():
            return 0
        try:
            with closing(self._connect_reference()) as conn:
                row = conn.execute("SELECT COUNT(*) FROM abbreviations").fetchone()
            return int(row[0])
        except (sqlite3.DatabaseError, OSError):
            return 0

    def needs_update(self, interval_hours: int) -> bool:
        if not self.capcodes_path.exists():
            return True
        value = self.metadata("capcodes_checked_at")
        if not value:
            return True
        try:
            last = datetime.fromisoformat(value)
        except ValueError:
            return True
        return datetime.now(UTC) - last >= timedelta(hours=interval_hours)

    def geocode_get(self, query: str) -> tuple[float, float] | None:
        return self.runtime.geocode_get(query)

    def geocode_put(self, query: str, latitude: float, longitude: float) -> None:
        self.runtime.geocode_put(query, latitude, longitude)

    def history_add(
        self,
        route_id: str,
        message_id: str,
        received_at: str,
        payload: dict,
        limit: int = 10,
    ) -> list[dict]:
        return self.runtime.history_add(route_id, message_id, received_at, payload, limit)

    def history_get(self, route_id: str, limit: int = 10) -> list[dict]:
        return self.runtime.history_get(route_id, limit)

    def update_from_url(self, url: str, min_records: int = 5000, timeout: int = 30) -> int:
        request = urllib.request.Request(url, headers={"User-Agent": "p2000-rtlsdr-mqtt/0.2"})
        with closing(urllib.request.urlopen(request, timeout=timeout)) as response:  # noqa: S310
            payload = response.read()
        return self.update_from_sqlite_bytes(payload, source=url, min_records=min_records)

    def update_from_sqlite_bytes(
        self,
        payload: bytes,
        source: str,
        min_records: int = 5000,
    ) -> int:
        if not payload.startswith(_SQLITE_MAGIC):
            raise ValueError("capcode source is not a SQLite database")

        digest = hashlib.sha256(payload).hexdigest()
        now = datetime.now(UTC).isoformat()
        current_digest = self.metadata("capcodes_source_sha256")
        if self.capcodes_path.exists() and digest == current_digest:
            count = self.record_count()
            self.runtime.metadata_set_many(
                {
                    "capcodes_checked_at": now,
                    "capcodes_source": source,
                    "capcodes_record_count": str(count),
                }
            )
            _LOG.info("Capcode database unchanged (%s records)", count)
            return count

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.capcodes_path.parent,
                prefix=f".{self.capcodes_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)

            count, abbreviation_count = _validate_source_database(temp_path, min_records)
            os.replace(temp_path, self.capcodes_path)
            temp_path = None

            self.runtime.metadata_set_many(
                {
                    "capcodes_source": source,
                    "capcodes_source_sha256": digest,
                    "capcodes_updated_at": now,
                    "capcodes_checked_at": now,
                    "capcodes_record_count": str(count),
                    "abbreviations_record_count": str(abbreviation_count),
                }
            )
            _LOG.info(
                "Installed capcode database: %s capcodes, %s abbreviations",
                count,
                abbreviation_count,
            )
            return count
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def _validate_source_database(path: Path, min_records: int) -> tuple[int, int]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        quick_check = conn.execute("PRAGMA quick_check").fetchone()
        if not quick_check or quick_check[0] != "ok":
            raise ValueError(f"SQLite quick_check failed: {quick_check!r}")

        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        missing_tables = _REQUIRED_SOURCE_TABLES - tables
        if missing_tables:
            missing = ", ".join(sorted(missing_tables))
            raise ValueError(f"capcode database misses required table(s): {missing}")

        capcode_columns = _table_columns(conn, "capcodes")
        missing_capcode_columns = _REQUIRED_CAPCODE_COLUMNS - capcode_columns
        if missing_capcode_columns:
            missing = ", ".join(sorted(missing_capcode_columns))
            raise ValueError(f"capcodes table misses required column(s): {missing}")

        meta_columns = _table_columns(conn, "capcodes_meta")
        missing_meta_columns = _REQUIRED_META_COLUMNS - meta_columns
        if missing_meta_columns:
            missing = ", ".join(sorted(missing_meta_columns))
            raise ValueError(f"capcodes_meta table misses required column(s): {missing}")

        count = int(conn.execute("SELECT COUNT(*) FROM capcodes").fetchone()[0])
        if count < min_records:
            raise ValueError(
                f"capcode database rejected: only {count} records (minimum {min_records})"
            )
        abbreviation_count = int(
            conn.execute("SELECT COUNT(*) FROM abbreviations").fetchone()[0]
        )
        return count, abbreviation_count
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None
