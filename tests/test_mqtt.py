from datetime import datetime, timezone

from p2000_receiver.config import RouteConfig
from p2000_receiver.models import P2000Message
from p2000_receiver.home_assistant import (
    history_attributes,
    history_entry,
    sensor_attributes,
    sensor_state,
)


def _message(body: str = "P 1 BR ALKMAAR Testmelding") -> P2000Message:
    return P2000Message(
        body=body,
        capcodes=["000123456", "000654321"],
        received_at=datetime(2026, 8, 22, 12, 34, 56, tzinfo=timezone.utc),
        source_time="2026-08-22 14:34:56",
        priority=1,
        disciplines=["Brandweer"],
        services=["Brandweer"],
        regions=["Noord-Holland Noord"],
        locations=["Alkmaar"],
        remarks=["Tankautospuit"],
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


def test_home_assistant_attributes_are_readable_and_keep_full_message():
    route = RouteConfig(id="alkmaar", name="P2000 Alkmaar")
    msg = _message()
    attrs = sensor_attributes(route, msg)

    assert attrs["message"] == msg.body
    assert attrs["time"] == "2026-08-22 14:34:56"
    assert attrs["priority"] == 1
    assert attrs["service"] == "Brandweer"
    assert attrs["discipline"] == "Brandweer"
    assert attrs["region"] == "Noord-Holland Noord"
    assert attrs["location"] == "Alkmaar"
    assert attrs["capcodes"] == ["000123456", "000654321"]
    assert attrs["capcodes_text"] == "000123456, 000654321"
    assert attrs["route_id"] == "alkmaar"


def test_home_assistant_attributes_omit_empty_optional_values():
    route = RouteConfig(id="all", name="P2000 alle meldingen")
    msg = P2000Message(
        body="Test",
        capcodes=[],
        received_at=datetime(2026, 8, 22, 12, 34, 56, tzinfo=timezone.utc),
    )
    attrs = sensor_attributes(route, msg)

    assert "priority" not in attrs
    assert "discipline" not in attrs
    assert "capcodes" not in attrs
    assert "postal_code" not in attrs


def test_history_entry_contains_service_and_capcodes():
    msg = _message()
    item = history_entry(msg)
    attrs = history_attributes(RouteConfig(id="all", name="Alle meldingen"), [item])

    assert item["service"] == "Brandweer"
    assert item["capcodes"] == ["000123456", "000654321"]
    assert attrs["count"] == 1
    assert attrs["messages"][0]["message"] == msg.body
