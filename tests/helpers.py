from __future__ import annotations

import sqlite3
from pathlib import Path


def make_reference_db(path: Path, records: list[dict] | None = None) -> Path:
    records = records or []
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE capcodes (
                    capcode TEXT PRIMARY KEY,
                    discipline TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    remark TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE capcodes_meta (
                    capcode TEXT PRIMARY KEY,
                    capcode_short TEXT NOT NULL,
                    service TEXT NOT NULL DEFAULT '',
                    region_code TEXT NOT NULL DEFAULT '',
                    station TEXT NOT NULL DEFAULT '',
                    unit_type TEXT NOT NULL DEFAULT '',
                    unit_type_name TEXT NOT NULL DEFAULT '',
                    callsign TEXT NOT NULL DEFAULT '',
                    unit_number TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    source_urls_json TEXT NOT NULL,
                    field_sources_json TEXT NOT NULL,
                    source_descriptions_json TEXT NOT NULL,
                    conflicts_json TEXT NOT NULL
                );
                CREATE TABLE abbreviations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    abbreviation TEXT NOT NULL,
                    meaning TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    source_record_id TEXT NOT NULL DEFAULT '',
                    observed_at TEXT NOT NULL DEFAULT ''
                );
                """
            )
            for record in records:
                code = record["capcode"]
                conn.execute(
                    "INSERT INTO capcodes VALUES(?,?,?,?,?,?)",
                    (
                        code,
                        record.get("discipline", ""),
                        record.get("region", ""),
                        record.get("location", ""),
                        record.get("description", ""),
                        record.get("remark", ""),
                    ),
                )
                conn.execute(
                    "INSERT INTO capcodes_meta VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        code,
                        code.lstrip("0") or "0",
                        record.get("service", ""),
                        record.get("region_code", ""),
                        record.get("station", ""),
                        record.get("unit_type", ""),
                        record.get("unit_type_name", ""),
                        record.get("callsign", ""),
                        record.get("unit_number", ""),
                        record.get("status", "ok"),
                        record.get("confidence", "high"),
                        "[]",
                        "[]",
                        "{}",
                        "{}",
                        "[]",
                    ),
                )
    finally:
        conn.close()
    return path
