from __future__ import annotations

import json
import os
import re
import unicodedata

from backend.app.agents.triage import anthropic_client

Language = str

SCRIPTS: dict[str, dict[str, str]] = {
    "en": {
        "on_track": "Sit down. Stay on this bus to {destination}.",
        "stops_left": "Stay seated. {stops} to go.",
        "almost_there": "Stay seated. The bus is almost at your stop.",
        "arrived": "Stand up now. This is your stop.",
        "tier1": "Stand up and get off at the next stop. Wait on the sidewalk.",
        "tier2": "Are you okay? Say yes, or press Help.",
        "tier3": "Stay where you are. A person is coming to help.",
        "help": "Stay where you are. A person is coming to help.",
        "ok": "Good. Stay seated. Guardian is still with you.",
        "confused": "Stay still. Get off at the next stop and wait.",
        "unknown": "Say yes if you are okay, or press Help.",
    },
    "vi": {
        "on_track": "Xin ngồi xuống. Ở lại xe này tới {destination}.",
        "stops_left": "Xin ngồi yên. Còn {stops}.",
        "almost_there": "Xin ngồi yên. Sắp tới trạm của bạn.",
        "arrived": "Đứng dậy. Đây là trạm của bạn.",
        "tier1": "Đứng dậy, xuống ở trạm tiếp theo, rồi đứng chờ.",
        "tier2": "Bạn ổn không? Nói có, hoặc nhấn Trợ giúp.",
        "tier3": "Ở nguyên chỗ. Có người đang tới giúp.",
        "help": "Ở nguyên chỗ. Có người đang tới giúp.",
        "ok": "Tốt. Xin ngồi yên. Guardian vẫn đi cùng bạn.",
        "confused": "Đứng yên. Xuống ở trạm tiếp theo rồi chờ.",
        "unknown": "Nói có nếu bạn ổn, hoặc nhấn Trợ giúp.",
    },
}

OK_PHRASES = {
    "yes", "yeah", "yep", "ok", "okay", "fine", "good", "im okay", "i am okay", "im fine",
    "vang", "vang a", "da", "on", "toi on", "toi o n", "duoc", "roi", "co",
}
HELP_PHRASES = {
    "help", "help me", "need help", "emergency", "please help",
    "giup", "giup toi", "cuu", "cuu toi", "tro giup",
}
CONFUSED_PHRASES = {
    "lost", "im lost", "i am lost", "dont know", "do not know", "confused", "where am i",
    "lac", "lac duong", "khong biet", "toi lac",
}


def language_code(preferred: str | None) -> Language:
    if preferred and preferred.lower().startswith("vi"):
        return "vi"
    return "en"


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", stripped)


def _has_phrase(folded: str, phrases: set[str]) -> bool:
    blob = f" {folded} "
    return any(f" {phrase} " in blob for phrase in phrases)


def spoken_instruction(
    escort_state: str,
    preferred_language: str | None,
    destination: str = "Westminster Clinic",
    stops_remaining: int | None = None,
    arrived: bool = False,
    help_requested: bool = False,
    intent: str | None = None,
) -> str:
    lang = language_code(preferred_language)
    scripts = SCRIPTS[lang]
    if intent == "ok":
        return scripts["ok"]
    if intent == "confused":
        return scripts["confused"]
    if intent == "unknown":
        return scripts["unknown"]
    if help_requested or intent == "needs_help":
        return scripts["help"]
    if escort_state == "tier1_redirect":
        return scripts["tier1"]
    if escort_state == "tier2_checkin":
        return scripts["tier2"]
    if escort_state == "tier3_dispatch":
        return scripts["tier3"]
    if arrived:
        return scripts["arrived"]
    if stops_remaining is None:
        return scripts["on_track"].format(destination=destination)
    if stops_remaining <= 0:
        return scripts["almost_there"]
    if lang == "vi":
        stop_label = f"{stops_remaining} trạm"
    else:
        stop_label = "1 stop" if stops_remaining == 1 else f"{stops_remaining} stops"
    return scripts["stops_left"].format(destination=destination, stops=stop_label)


def interpret_rider_reply(transcript: str, preferred_language: str | None = None) -> dict:
    folded = " ".join(_fold(transcript).split())
    if not folded:
        return {"intent": "unknown", "transcript": transcript}
    if _has_phrase(folded, HELP_PHRASES):
        return {"intent": "needs_help", "transcript": transcript}
    if _has_phrase(folded, CONFUSED_PHRASES):
        return {"intent": "confused", "transcript": transcript}
    if _has_phrase(folded, OK_PHRASES):
        return {"intent": "ok", "transcript": transcript}
    if llm_enabled():
        classified = _llm_interpret(transcript, preferred_language)
        if classified:
            return classified
    return {"intent": "unknown", "transcript": transcript}


def llm_enabled() -> bool:
    return os.getenv("GUARDIAN_USE_LLM", "1").lower() not in {"0", "false", "no"}


def generate_guidance(context: dict) -> str:
    fallback = spoken_instruction(
        escort_state=context.get("escort_state") or "on_track",
        preferred_language=context.get("preferred_language"),
        destination=context.get("destination") or "Westminster Clinic",
        stops_remaining=context.get("stops_remaining"),
        arrived=bool(context.get("arrived")),
        help_requested=bool(context.get("help_requested")),
        intent=context.get("intent"),
    )
    if not llm_enabled():
        return fallback
    client = anthropic_client()
    if client is None:
        return fallback
    language = language_code(context.get("preferred_language"))
    prompt = (
        "You are Guardian, a calm voice companion for a bus rider. "
        "Return only JSON {\"instruction\": \"...\"} with ONE short sentence. "
        "Describe a physical action (sit, stand, get off, wait, stay). "
        "No route numbers, no GTFS jargon, no street-code names, no disability labels. "
        "12 words or fewer. Write in Vietnamese if language is vi, otherwise English.\n"
        f"Context: {json.dumps({**context, 'language': language}, ensure_ascii=False)}"
    )
    try:
        response = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            max_tokens=80,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = _parse_json(response.content[0].text)
        instruction = str(parsed.get("instruction", "")).strip()
        if 3 <= len(instruction) <= 140:
            return instruction
    except Exception:
        return fallback
    return fallback


def _llm_interpret(transcript: str, preferred_language: str | None) -> dict | None:
    client = anthropic_client()
    if client is None:
        return None
    prompt = (
        "Classify the rider's spoken reply. Return only JSON "
        '{"intent":"ok|confused|needs_help|unknown"} '
        "ok means they are fine, needs_help means they want a person now, "
        "confused means they are lost or do not understand.\n"
        f"Language hint: {language_code(preferred_language)}. Reply: {transcript}"
    )
    try:
        response = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            max_tokens=40,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = _parse_json(response.content[0].text)
        intent = parsed.get("intent")
        if intent in {"ok", "confused", "needs_help", "unknown"}:
            return {"intent": intent, "transcript": transcript}
    except Exception:
        return None
    return None


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).removesuffix("```").strip()
    return json.loads(cleaned)
