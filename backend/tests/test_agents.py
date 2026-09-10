from datetime import datetime, timedelta, timezone

from backend.app.agents.route_compliance import evaluate_route_compliance
from backend.app.agents.triage import generate_triage
from backend.app.gtfs.static_data import ON_ROUTE_TRACE, WRONG_BUS_TRACE, resolve_destination


def test_destination_resolution_matches_seeded_clinic() -> None:
    result = resolve_destination("Westminster Clinic")

    assert result["destination"]["name"] == "Westminster Clinic"
    assert result["route"]["id"] == "oc43"


def test_route_compliance_accepts_on_route_trace() -> None:
    locations = [{"lat": lat, "lon": lon, "recorded_at": datetime.now(timezone.utc).isoformat()} for lat, lon in ON_ROUTE_TRACE]

    result = evaluate_route_compliance(locations)

    assert result["status"] == "on_track"
    assert result["severity"] == "green"


def test_route_compliance_flags_wrong_bus_trace() -> None:
    locations = [{"lat": lat, "lon": lon, "recorded_at": datetime.now(timezone.utc).isoformat()} for lat, lon in WRONG_BUS_TRACE]

    result = evaluate_route_compliance(locations)

    assert result["deviation_type"] in {"wrong_bus", "outside_corridor"}
    assert result["severity"] == "red"


def test_route_compliance_flags_stationary_trace() -> None:
    start = datetime.now(timezone.utc)
    locations = [
        {"lat": 33.7444, "lon": -117.9726, "recorded_at": start.isoformat()},
        {"lat": 33.74441, "lon": -117.97261, "recorded_at": (start + timedelta(minutes=16)).isoformat()},
        {"lat": 33.74442, "lon": -117.97262, "recorded_at": (start + timedelta(minutes=31)).isoformat()},
    ]

    result = evaluate_route_compliance(locations)

    assert result["deviation_type"] == "stationary_too_long"
    assert result["severity"] == "yellow"


def test_triage_fallback_returns_dispatcher_copy() -> None:
    result = generate_triage(
        {
            "rider_name": "Mr. Nguyen",
            "destination_name": "Westminster Clinic",
            "deviation_type": "wrong_bus",
        }
    )

    assert "Mr. Nguyen" in result["summary"]
    assert "wrong bus" in result["summary"]
    assert result["recommended_action"]
    assert result["rider_phrase"]
