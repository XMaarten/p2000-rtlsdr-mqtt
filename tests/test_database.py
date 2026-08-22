from p2000_receiver.database import CapcodeDatabase


def test_csv_update_preserves_other_tables(tmp_path):
    db = CapcodeDatabase(str(tmp_path / "db.sqlite3"))
    db.geocode_put("1811AB, Netherlands", 52.0, 4.0)
    csv_data = (
        "Capcode;Discipline;Regio;Regiocode;Korps;Omschrijving;Short\n"
        "1234567;Brandweer;Noord-Holland Noord;BRWNHN;Alkmaar;Tankautospuit;TS\n"
        "1234568;Ambulance;Noord-Holland Noord;AMBNHN;Hoorn;Ambulance;Ambu\n"
    ).encode()
    count = db.update_from_csv_bytes(csv_data, source="test", min_records=2)
    assert count == 2
    assert db.lookup_many(["001234567"])[0].location == "Alkmaar"
    assert db.geocode_get("1811AB, Netherlands") == (52.0, 4.0)
    db.close()


def test_csv_update_handles_duplicate_capcodes(tmp_path):
    db = CapcodeDatabase(str(tmp_path / "db.sqlite3"))
    csv_data = (
        "Capcode;Discipline;Regio;Regiocode;Korps;Omschrijving;Short\n"
        "1433120;Politie;Zuid-Holland Zuid;POLZHZ;Dordrecht;Lokaal beheer;Beheer\n"
        "1433120;Politie;Zuid-Holland Zuid;POLZHZ;Dordrecht;Lokaal beheer GMC Prio 1;Prio 1\n"
        "1234568;Ambulance;Noord-Holland Noord;AMBNHN;Hoorn;Ambulance;Ambu\n"
    ).encode()

    count = db.update_from_csv_bytes(csv_data, source="test", min_records=2)

    assert count == 2
    info = db.lookup_many(["001433120"])[0]
    assert info.remark == "Lokaal beheer GMC Prio 1"
    assert db.record_count() == 2
    db.close()


def test_route_history_is_persistent_and_limited(tmp_path):
    path = str(tmp_path / "history.sqlite3")
    db = CapcodeDatabase(path)
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

    reopened = CapcodeDatabase(path)
    restored = reopened.history_get("all", 10)
    assert len(restored) == 10
    assert restored[0]["message"] == "message 11"
    reopened.close()
