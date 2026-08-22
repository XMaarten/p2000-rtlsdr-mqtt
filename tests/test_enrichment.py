from datetime import UTC, datetime

from p2000_receiver.database import CapcodeDatabase
from p2000_receiver.enrichment import enrich
from p2000_receiver.models import RawPage

from .helpers import make_reference_db


def test_metadata_from_all_capcodes_is_aggregated(tmp_path):
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
            },
            {
                "capcode": "001234568",
                "discipline": "Ambulance",
                "service": "Ambulance",
                "region": "Noord-Holland Noord",
                "region_code": "AMBNHN",
                "location": "Hoorn",
            },
        ],
    )
    db = CapcodeDatabase(capcodes, tmp_path / "runtime.sqlite3")
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
    capcodes = make_reference_db(
        tmp_path / "capcodes.sqlite3",
        [
            {
                "capcode": "001234567",
                "discipline": "Politie",
                "service": "Politie",
                "region": "Test",
                "location": "Test",
                "description": "Meldkamer",
            }
        ],
    )
    db = CapcodeDatabase(capcodes, tmp_path / "runtime.sqlite3")

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


def test_enrichment_exposes_rich_p2000_capcode_metadata(tmp_path):
    capcodes = make_reference_db(
        tmp_path / "capcodes.sqlite3",
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
    db = CapcodeDatabase(capcodes, tmp_path / "runtime.sqlite3")
    page = RawPage(
        body="P 1 BR Aalsmeer",
        capcodes=("000100001",),
        received_at=datetime.now(UTC),
    )
    msg = enrich(page, db)
    assert msg.services == ["Brandweer"]
    assert msg.stations == ["Aalsmeer"]
    assert msg.descriptions == ["Tankautospuit-612"]
    assert msg.unit_type_names == ["Tankautospuit"]
    assert msg.callsigns == ["TS-3531"]
    assert msg.unit_numbers == ["612"]
    db.close()
