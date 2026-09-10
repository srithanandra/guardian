from backend.app.agents.escort_scripts import generate_guidance, interpret_rider_reply, spoken_instruction
from backend.app.gtfs.static_data import ON_ROUTE_TRACE, WRONG_BUS_TRACE, journey_milestones


def test_spoken_instructions_are_bilingual():
    english = spoken_instruction("tier1_redirect", "en", destination="Westminster Clinic")
    vietnamese = spoken_instruction("tier1_redirect", "vi", destination="Westminster Clinic")

    assert "get off" in english.lower()
    assert "xuống" in vietnamese.lower()
    assert english != vietnamese
    assert "route 43" not in english.lower()


def test_generate_guidance_falls_back_without_llm():
    english = generate_guidance({"escort_state": "tier1_redirect", "preferred_language": "en", "destination": "Westminster Clinic"})
    vietnamese = generate_guidance({"escort_state": "tier1_redirect", "preferred_language": "vi", "destination": "Westminster Clinic"})

    assert english == spoken_instruction("tier1_redirect", "en", destination="Westminster Clinic")
    assert vietnamese == spoken_instruction("tier1_redirect", "vi", destination="Westminster Clinic")


def test_interpret_rider_replies_in_english_and_vietnamese():
    assert interpret_rider_reply("Yes, I'm okay")["intent"] == "ok"
    assert interpret_rider_reply("Vâng, tôi ổn")["intent"] == "ok"
    assert interpret_rider_reply("I'm lost")["intent"] == "confused"
    assert interpret_rider_reply("Tôi lạc đường")["intent"] == "confused"
    assert interpret_rider_reply("help")["intent"] == "needs_help"
    assert interpret_rider_reply("Giúp tôi")["intent"] == "needs_help"


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


def test_language_switch_keeps_the_same_route(client):
    trip = client.post("/trips", json={"destination": "Westminster Clinic"}).json()

    english = client.patch("/riders/rider_nguyen/language", json={"preferred_language": "en"}).json()
    vietnamese = client.patch("/riders/rider_nguyen/language", json={"preferred_language": "vi"}).json()

    assert trip["route_name"] == english["trip"]["route_name"] == vietnamese["trip"]["route_name"]
    assert "sit" in english["trip"]["spoken_instruction"].lower() or "stay" in english["trip"]["spoken_instruction"].lower()
    assert english["trip"]["spoken_instruction"] != vietnamese["trip"]["spoken_instruction"]


def test_ok_reply_holds_tier_two(client):
    trip = client.post("/trips", json={"destination": "Westminster Clinic"}).json()
    for lat, lon in WRONG_BUS_TRACE:
        client.post(f"/trips/{trip['id']}/locations", json={"lat": lat, "lon": lon, "source": "test"})
    snapshot = client.get("/snapshot").json()
    client.post(f"/alerts/{snapshot['alerts'][0]['id']}/escalate")

    replied = client.post(f"/trips/{trip['id']}/reply", json={"transcript": "yes"}).json()

    assert replied["interpretation"]["intent"] == "ok"
    assert replied["trip"]["escort_state"] == "tier2_checkin"
    assert replied["trip"]["last_reply_intent"] == "ok"
    assert replied["trip"]["alerts"][0]["tier"] == 2


def test_help_reply_jumps_to_tier_three(client):
    trip = client.post("/trips", json={"destination": "Westminster Clinic"}).json()

    replied = client.post(f"/trips/{trip['id']}/reply", json={"transcript": "help"}).json()

    assert replied["interpretation"]["intent"] == "needs_help"
    assert replied["trip"]["escort_state"] == "tier3_dispatch"
    assert replied["trip"]["alerts"][0]["tier"] == 3


def test_confused_reply_starts_tier_one(client):
    trip = client.post("/trips", json={"destination": "Westminster Clinic"}).json()

    replied = client.post(f"/trips/{trip['id']}/reply", json={"transcript": "I'm lost"}).json()

    assert replied["interpretation"]["intent"] == "confused"
    assert replied["trip"]["escort_state"] == "tier1_redirect"
    assert replied["trip"]["alerts"][0]["deviation_type"] == "confused"


def test_journey_milestones_without_http():
    empty = journey_milestones("OC Bus Route 43", [])
    arrived = journey_milestones(
        "OC Bus Route 43",
        [{"lat": 33.7596, "lon": -117.9892}],
    )

    assert empty[0]["complete"] is True
    assert empty[-1]["complete"] is False
    assert arrived[-1]["complete"] is True


def test_tts_without_keys_is_unavailable(client):
    response = client.post("/tts", json={"text": "Stay seated.", "language": "en-US"})

    assert response.status_code == 503
