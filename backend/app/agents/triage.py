from __future__ import annotations

import json
import os
from functools import lru_cache


CACHED_TRIAGE = {
    "severity": "significant",
    "summary": "Mr. Nguyen appears to be on the wrong bus and is moving away from Westminster Clinic.",
    "recommended_action": "Claim the alert and call the rider. Ask him to exit at the next safe stop and wait for dispatcher guidance.",
    "rider_phrase": "Wrong bus. Please exit at the next stop.",
}


def _fallback_triage(event: dict) -> dict:
    rider_name = event.get("rider_name", "The rider")
    deviation_type = event.get("deviation_type", "route deviation").replace("_", " ")
    destination = event.get("destination_name", "the destination")
    readable_deviation = {
        "outside corridor": "outside the route corridor",
        "wrong bus": "on the wrong bus",
        "wrong direction": "moving in the wrong direction",
    }.get(deviation_type, f"showing a {deviation_type}")
    if deviation_type == "stationary too long":
        return {
            "severity": "mild",
            "summary": f"{rider_name} has been stationary longer than expected while traveling to {destination}.",
            "recommended_action": "Call the rider to confirm they are safe and still waiting intentionally.",
            "rider_phrase": "Please wait. A Guardian volunteer may call you.",
        }
    if deviation_type == "help requested":
        return {
            "severity": "critical",
            "summary": f"{rider_name} pressed Help while traveling to {destination}.",
            "recommended_action": "Call the rider now and stay on the line until they are safe.",
            "rider_phrase": "Help is on the way. Stay where you are.",
        }
    return {
        **CACHED_TRIAGE,
        "summary": f"{rider_name} is {readable_deviation} while traveling to {destination}. They may need immediate guidance.",
    }


@lru_cache(maxsize=1)
def _anthropic_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except Exception:
        return None
    return Anthropic(api_key=api_key)


def generate_triage(event: dict) -> dict:
    client = _anthropic_client()
    if client is None:
        return _fallback_triage(event)

    prompt = (
        "You are Guardian's transit dispatcher triage agent. Return only JSON with keys "
        "severity, summary, recommended_action, rider_phrase. Keep rider_phrase under 10 words. "
        f"Event: {json.dumps(event, ensure_ascii=False)}"
    )
    try:
        response = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            max_tokens=400,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        parsed = json.loads(text)
        return {**_fallback_triage(event), **parsed}
    except Exception:
        return _fallback_triage(event)
