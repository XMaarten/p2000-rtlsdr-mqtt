from datetime import UTC, datetime

from p2000_receiver.config import RouteConfig
from p2000_receiver.home_assistant import (
    history_attributes,
    history_entry,
    local_event_time,
    sensor_attributes,
    sensor_state,
)
from p2000_receiver.models import CapcodeInfo, P2000Message


def _message(body: str = "P 1 BR ALKMAAR Testmelding") -> P2000Message:
    details = [
        CapcodeInfo(
            capcode="000123456",
            discipline="Brandweer",
            service="Brandweer",
            region="Noord-Holland Noord",
            location="Alkmaar",
            station="Alkmaar",
            unit_type="TS",
            unit_type_name="Tankautospuit",
            callsign="TS-1031",
            description="Tankautospuit-612",
        ),
        CapcodeInfo(
            capcode="000654321",
            discipline="Brandweer",
            service="Brandweer",
            region="Noord-Holland Noord",
            station="Alkmaar",
            description="Bezetting TS",
        ),
    ]
    return P2000Message(
        body=body,
        capcodes=["000123456", "000654321"],
        received_at=datetime(2026, 8, 22, 12, 34, 56, tzinfo=UTC),
        # multimon-ng FLEX source timestamp is UTC without a timezone suffix.
        source_time="2026-08-22 12:34:56",
        priority=1,
        disciplines=["Brandweer"],
        services=["Brandweer"],
        regions=["Noord-Holland Noord"],
        locations=["Alkmaar"],
        stations=["Alkmaar"],
        unit_types=["TS"],
        unit_type_names=["Tankautospuit"],
        callsigns=["TS-1031"],
        unit_numbers=["612"],
        remarks=["Tankautospuit"],
        capcode_details=details,
        postal_code="1711AA",
        latitude=52.65,
        longitude=4.95,
    )


def test_home_assistant_state_is_short_and_normalized():
    msg = _message("P 1   " + "X" * 300)
    state = sensor_state(msg)
    assert len(state) <= 200
    assert state.endswith("...")
    assert "   " not in state


def test_home_assistant_time_is_local_amsterdam_summer_time():
    msg = _message()
    assert local_event_time(msg) == "2026-08-22 14:34:56"


def test_home_assistant_time_handles_winter_time():
    msg = P2000Message(
        body="Test",
        capcodes=[],
        received_at=datetime(2026, 1, 22, 12, 34, 56, tzinfo=UTC),
        source_time="2026-01-22 12:34:56",
    )
    assert local_event_time(msg) == "2026-01-22 13:34:56"


def test_home_assistant_attributes_are_readable_and_keep_full_message():
    route = RouteConfig(id="alkmaar", name="P2000 Alkmaar")
    msg = _message()
    attrs = sensor_attributes(route, msg)

    assert attrs["message"] == msg.body
    assert attrs["time"] == "2026-08-22 14:34:56"
    assert attrs["source_time"] == "2026-08-22 12:34:56"
    assert attrs["event_time_utc"] == "2026-08-22T12:34:56+00:00"
    assert attrs["priority"] == 1
    assert attrs["service"] == "Brandweer"
    assert attrs["discipline"] == "Brandweer"
    assert attrs["region"] == "Noord-Holland Noord"
    assert attrs["location"] == "Alkmaar"
    assert attrs["capcodes"] == ["000123456", "000654321"]
    assert attrs["capcodes_text"] == "000123456, 000654321"
    assert attrs["route_id"] == "alkmaar"
    assert attrs["callsign"] == "TS-1031"
    assert attrs["unit_type_name"] == "Tankautospuit"
    assert attrs["unit_number"] == "612"
    assert attrs["units"][0].startswith("Brandweer · Alkmaar · TS-1031 · Tankautospuit")
    assert attrs["capcode_details"][0].startswith("000123456 — Brandweer · Alkmaar")


def test_home_assistant_attributes_omit_empty_optional_values():
    route = RouteConfig(id="all", name="P2000 alle meldingen")
    msg = P2000Message(
        body="Test",
        capcodes=[],
        received_at=datetime(2026, 8, 22, 12, 34, 56, tzinfo=UTC),
    )
    attrs = sensor_attributes(route, msg)

    assert "priority" not in attrs
    assert "discipline" not in attrs
    assert "capcodes" not in attrs
    assert "postal_code" not in attrs
    assert "units" not in attrs


def test_history_entry_contains_units_details_and_local_time():
    msg = _message()
    item = history_entry(msg)
    attrs = history_attributes(RouteConfig(id="all", name="Alle meldingen"), [item])

    assert item["time"] == "2026-08-22 14:34:56"
    assert item["service"] == "Brandweer"
    assert item["capcodes"] == ["000123456", "000654321"]
    assert item["callsign"] == "TS-1031"
    assert item["unit_number"] == "612"
    assert item["units"]
    assert item["capcode_details"]
    assert attrs["count"] == 1
    assert attrs["messages"][0]["message"] == msg.body
