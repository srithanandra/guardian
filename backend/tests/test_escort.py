from backend.app.agents.escort_scripts import spoken_instruction
from backend.app.gtfs.static_data import ON_ROUTE_TRACE, WRONG_BUS_TRACE, journey_milestones


def test_spoken_instructions_are_bilingual():
    english = spoken_instruction("tier1_redirect", "en", destination="Westminster Clinic")
    vietnamese = spoken_instruction("tier1_redirect", "vi", destination="Westminster Clinic")

    assert "Get off" in english
    assert "Xuống" in vietnamese
    assert english != vietnamese


def test_help_jumps_to_tier_three(client):
    trip = client.post("/trips", json={"destination": "Westminster Clinic"}).json()

    helped = client.post(f"/trips/{trip['id']}/help").json()

    assert helped["escort_state"] == "tier3_dispatch"
    assert helped["alerts"][0]["tier"] == 3
    payload = helped["alerts"][0]["escalation_payload"]
    assert payload["rider_name"] == "Mr. Nguyen"
    assert payload["destination"] == "Westminster Clinic"
    assert payload["care_notes"]
    assert payload["mocked"] is True
    assert "Stay" in helped["spoken_instruction"] or "nguyên" in helped["spoken_instruction"]


def test_escalation_chain_notifies_companion(client):
    trip = client.post("/trips", json={"destination": "Westminster Clinic"}).json()
    for lat, lon in WRONG_BUS_TRACE:
        client.post(f"/trips/{trip['id']}/locations", json={"lat": lat, "lon": lon, "source": "test"})

    snapshot = client.get("/snapshot").json()
    alert = snapshot["alerts"][0]
    assert alert["tier"] == 1
    assert snapshot["trips"][0]["escort_state"] == "tier1_redirect"

    tier2 = client.post(f"/alerts/{alert['id']}/escalate").json()
    assert tier2["tier"] == 2
    assert tier2["companion_notified"] is True

    tier3 = client.post(f"/alerts/{alert['id']}/escalate").json()
    assert tier3["tier"] == 3
    assert tier3["escalation_payload"]["last_known_location"]
    assert tier3["escalation_payload"]["care_notes"]


def test_milestones_advance_on_route(client):
    trip = client.post("/trips", json={"destination": "Westminster Clinic"}).json()
    for lat, lon in ON_ROUTE_TRACE:
        client.post(f"/trips/{trip['id']}/locations", json={"lat": lat, "lon": lon, "source": "test"})

    updated = client.get(f"/trips/{trip['id']}").json()
    labels = {item["label"]: item["complete"] for item in updated["milestones"]}
    assert labels["Trip confirmed"] is True
    assert any(complete for label, complete in labels.items() if label.startswith("Board"))
    assert labels["Arrived"] is True
    assert updated["escort_state"] == "on_track"


def test_demo_reuses_existing_trip(client):
    trip = client.post("/trips", json={"destination": "Westminster Clinic"}).json()

    played = client.post("/demo/run/wrong-bus").json()

    assert played["id"] == trip["id"]
    assert played["locations"]
    assert played["escort_state"] == "tier1_redirect"


def test_journey_milestones_without_http():
    empty = journey_milestones("OC Bus Route 43", [])
    arrived = journey_milestones(
        "OC Bus Route 43",
        [{"lat": 33.7596, "lon": -117.9892}],
    )

    assert empty[0]["complete"] is True
    assert empty[-1]["complete"] is False
    assert arrived[-1]["complete"] is True
