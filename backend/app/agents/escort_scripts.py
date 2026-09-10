from __future__ import annotations

Language = str

SCRIPTS: dict[str, dict[str, str]] = {
    "en": {
        "on_track": "Riding the 43 toward {destination}. Stay seated.",
        "stops_left": "Riding toward {destination}. {stops} to go.",
        "almost_there": "Almost there. Stay seated.",
        "arrived": "You have arrived. Stay put.",
        "tier1": "Get off at the next stop and wait.",
        "tier2": "Are you okay? Press Help if you need a person.",
        "tier3": "Help is on the way. Stay where you are.",
        "help": "Help is on the way. Stay where you are.",
    },
    "vi": {
        "on_track": "Đang đi tuyến 43 tới {destination}. Xin ngồi yên.",
        "stops_left": "Đang đi tới {destination}. Còn {stops}.",
        "almost_there": "Sắp tới nơi. Xin ngồi yên.",
        "arrived": "Bạn đã tới nơi. Xin ở nguyên chỗ.",
        "tier1": "Xuống ở trạm tiếp theo và đứng chờ.",
        "tier2": "Bạn ổn không? Nhấn Trợ giúp nếu cần người.",
        "tier3": "Người giúp đang tới. Xin ở nguyên chỗ.",
        "help": "Người giúp đang tới. Xin ở nguyên chỗ.",
    },
}


def language_code(preferred: str | None) -> Language:
    if preferred and preferred.lower().startswith("vi"):
        return "vi"
    return "en"


def spoken_instruction(
    escort_state: str,
    preferred_language: str | None,
    destination: str = "Westminster Clinic",
    stops_remaining: int | None = None,
    arrived: bool = False,
    help_requested: bool = False,
) -> str:
    lang = language_code(preferred_language)
    scripts = SCRIPTS[lang]
    if help_requested:
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
