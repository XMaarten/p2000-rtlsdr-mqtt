from datetime import UTC, datetime

from p2000_receiver.config import GlobalFilterConfig, MatchConfig, RouteConfig
from p2000_receiver.filters import globally_ignored, route_matches
from p2000_receiver.models import P2000Message


def message():
    return P2000Message(
        body="P 1 Brand Alkmaar",
        capcodes=["001234567", "001234568"],
        received_at=datetime.now(UTC),
        disciplines=["Brandweer", "Ambulance"],
        regions=["Noord-Holland Noord", "Landelijk"],
        locations=["Alkmaar"],
        remarks=["Tankautospuit"],
    )


def test_route_ands_fields_and_ors_values():
    route = RouteConfig(
        id="x",
        name="x",
        include=MatchConfig(disciplines=["Brandweer"], regions=["Noord-Holland Noord", "Utrecht"]),
    )
    assert route_matches(message(), route)


def test_exclude_rejects():
    route = RouteConfig(id="x", name="x", exclude=MatchConfig(text=["*Alkmaar*"]))
    assert not route_matches(message(), route)


def test_ignore_capcodes_any_and_all():
    msg = message()
    assert globally_ignored(
        msg, GlobalFilterConfig(ignore_capcodes=["001234567"], ignore_capcodes_mode="any")
    )
    assert not globally_ignored(
        msg, GlobalFilterConfig(ignore_capcodes=["001234567"], ignore_capcodes_mode="all")
    )
