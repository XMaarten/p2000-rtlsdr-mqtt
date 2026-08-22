from datetime import UTC, datetime

from p2000_receiver.database import CapcodeDatabase
from p2000_receiver.enrichment import enrich
from p2000_receiver.models import RawPage


def test_metadata_from_all_capcodes_is_aggregated(tmp_path):
    db = CapcodeDatabase(str(tmp_path / "test.sqlite3"))
    with db.conn:
        db.conn.executemany(
            "INSERT INTO capcodes(capcode,discipline,region,region_code,location,remark,short) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                ("001234567", "Brandweer", "Noord-Holland Noord", "BRWNHN", "Alkmaar", "TS", "TS"),
                (
                    "001234568",
                    "Ambulance",
                    "Noord-Holland Noord",
                    "AMBNHN",
                    "Hoorn",
                    "Ambu",
                    "Ambu",
                ),
            ],
        )
    page = RawPage(
        body="P 1 melding 1811AB",
        capcodes=("001234567", "001234568"),
        received_at=datetime.now(UTC),
    )
    msg = enrich(page, db)
    assert msg.disciplines == ["Brandweer", "Ambulance"]
    assert msg.locations == ["Alkmaar", "Hoorn"]
    assert msg.postal_code == "1811AB"
    assert msg.priority == 1
    db.close()


def test_service_detection_uses_metadata_and_message_fallback(tmp_path):
    db = CapcodeDatabase(str(tmp_path / "services.sqlite3"))
    with db.conn:
        db.conn.execute(
            "INSERT INTO capcodes(capcode,discipline,region,region_code,location,remark,short) "
            "VALUES(?,?,?,?,?,?,?)",
            ("001234567", "Politie", "Test", "POL", "Test", "Meldkamer", "POL"),
        )

    police = RawPage(
        body="Melding test",
        capcodes=("001234567",),
        received_at=datetime.now(UTC),
    )
    ambulance = RawPage(
        body="A1 Alkmaar 1711AA",
        capcodes=("009999999",),
        received_at=datetime.now(UTC),
    )
    fire = RawPage(
        body="P 1 BR Alkmaar brand",
        capcodes=("009999998",),
        received_at=datetime.now(UTC),
    )

    assert enrich(police, db).services == ["Politie"]
    assert enrich(ambulance, db).services == ["Ambulance"]
    assert enrich(fire, db).services == ["Brandweer"]
    db.close()
