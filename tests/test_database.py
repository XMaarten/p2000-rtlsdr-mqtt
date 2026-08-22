import sqlite3

import pytest

from p2000_receiver.database import CapcodeDatabase

from .helpers import make_reference_db


def test_reference_lookup_and_runtime_state_are_separate(tmp_path):
    capcodes = make_reference_db(
        tmp_path / "capcodes.sqlite3",
        [
            {
                "capcode": "001234567",
                "discipline": "Brandweer",
                "service": "Brandweer",
                "region": "Noord-Holland Noord",
                "region_code": "BRWNHN",
                "location": "Alkmaar",
                "station": "Alkmaar",
                "description": "Tankautospuit-612",
                "unit_type": "TS",
                "unit_type_name": "Tankautospuit",
                "callsign": "TS-3531",
                "unit_number": "612",
            }
        ],
    )
    runtime = tmp_path / "runtime.sqlite3"
    db = CapcodeDatabase(capcodes, runtime)

    info = db.lookup_many(["001234567"])[0]
    assert info.location == "Alkmaar"
    assert info.callsign == "TS-3531"

    db.geocode_put("Alkmaar", 52.63, 4.75)
    db.history_add("all", "msg-1", "2026-08-22T12:00:00+00:00", {"message": "test"})
    db.close()

    assert runtime.exists()
    runtime_conn = sqlite3.connect(runtime)
    try:
        tables = {
            row[0]
            for row in runtime_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        runtime_conn.close()
    assert "capcodes" not in tables
    assert {"metadata", "geocode_cache", "route_history"}.issubset(tables)


def test_route_history_is_persistent_and_limited(tmp_path):
    capcodes = make_reference_db(tmp_path / "capcodes.sqlite3")
    runtime = tmp_path / "runtime.sqlite3"
    db = CapcodeDatabase(capcodes, runtime)
    for i in range(12):
        history = db.history_add(
            "all",
            f"id-{i}",
            f"2026-08-22T12:{i:02d}:00+00:00",
            {"id": f"id-{i}", "message": f"message {i}"},
            limit=10,
        )
    assert len(history) == 10
    assert history[0]["id"] == "id-11"
    assert history[-1]["id"] == "id-2"
    db.close()

    reopened = CapcodeDatabase(capcodes, runtime)
    restored = reopened.history_get("all", 10)
    assert len(restored) == 10
    assert restored[0]["message"] == "message 11"
    reopened.close()


def test_sqlite_update_replaces_only_reference_database(tmp_path):
    source = make_reference_db(
        tmp_path / "source.sqlite3",
        [
            {
                "capcode": "000100001",
                "discipline": "Brandweer",
                "service": "Brandweer",
                "region": "Amsterdam-Amstelland",
                "region_code": "BRWAA",
                "location": "Aalsmeer",
                "station": "Aalsmeer",
                "description": "Tankautospuit-612",
                "unit_type": "TS",
                "unit_type_name": "Tankautospuit",
                "callsign": "TS-3531",
                "unit_number": "612",
            }
        ],
    )
    source_conn = sqlite3.connect(source)
    with source_conn:
        source_conn.execute(
            "INSERT INTO abbreviations(abbreviation,meaning,category) VALUES(?,?,?)",
            ("TS", "Tankautospuit", "vehicle"),
        )
    source_conn.close()

    capcodes = tmp_path / "installed-capcodes.sqlite3"
    runtime = tmp_path / "runtime.sqlite3"
    db = CapcodeDatabase(capcodes, runtime)
    db.geocode_put("Aalsmeer", 52.26, 4.75)
    db.history_add("all", "msg-1", "2026-08-22T12:00:00+00:00", {"message": "test"})

    count = db.update_from_sqlite_bytes(
        source.read_bytes(), source="github:test", min_records=1
    )

    assert count == 1
    assert capcodes.read_bytes() == source.read_bytes()
    info = db.lookup_many(["000100001"])[0]
    assert info.service == "Brandweer"
    assert info.station == "Aalsmeer"
    assert info.unit_type == "TS"
    assert info.callsign == "TS-3531"
    assert db.abbreviation_count() == 1
    assert db.geocode_get("Aalsmeer") == (52.26, 4.75)
    assert db.history_get("all")[0]["message"] == "test"
    db.close()


def test_sqlite_update_rejects_csv_and_keeps_existing_reference(tmp_path):
    installed = make_reference_db(
        tmp_path / "capcodes.sqlite3",
        [{"capcode": "000100001", "discipline": "Brandweer"}],
    )
    original = installed.read_bytes()
    db = CapcodeDatabase(installed, tmp_path / "runtime.sqlite3")

    with pytest.raises(ValueError, match="not a SQLite"):
        db.update_from_sqlite_bytes(b"capcode;discipline\n1;Brandweer\n", "test", 1)

    assert installed.read_bytes() == original
    db.close()


def test_sqlite_update_rejects_missing_required_tables(tmp_path):
    broken = tmp_path / "broken.sqlite3"
    conn = sqlite3.connect(broken)
    with conn:
        conn.execute("CREATE TABLE capcodes(capcode TEXT PRIMARY KEY)")
    conn.close()

    db = CapcodeDatabase(tmp_path / "capcodes.sqlite3", tmp_path / "runtime.sqlite3")
    with pytest.raises(ValueError, match="required table"):
        db.update_from_sqlite_bytes(broken.read_bytes(), "test", 1)
    assert not (tmp_path / "capcodes.sqlite3").exists()
    db.close()


def test_unchanged_source_updates_check_timestamp(tmp_path):
    source = make_reference_db(
        tmp_path / "source.sqlite3",
        [{"capcode": "000100001", "discipline": "Brandweer"}],
    )
    db = CapcodeDatabase(tmp_path / "capcodes.sqlite3", tmp_path / "runtime.sqlite3")
    payload = source.read_bytes()
    db.update_from_sqlite_bytes(payload, "test", 1)
    first_hash = db.metadata("capcodes_source_sha256")
    assert db.update_from_sqlite_bytes(payload, "test", 1) == 1
    assert db.metadata("capcodes_source_sha256") == first_hash
    assert db.metadata("capcodes_checked_at") is not None
    db.close()
