from __future__ import annotations

import os
import xml.sax.saxutils as xml
from functools import lru_cache

import httpx

AZURE_VOICE = {
    "vi": "vi-VN-HoaiMyNeural",
    "en": "en-US-JennyNeural",
}
OPENAI_VOICE = {
    "vi": "nova",
    "en": "nova",
}


def language_family(language: str | None) -> str:
    if language and language.lower().startswith("vi"):
        return "vi"
    return "en"


def tts_provider() -> str | None:
    if os.getenv("GUARDIAN_TTS", "1").lower() in {"0", "false", "no"}:
        return None
    if os.getenv("AZURE_SPEECH_KEY") and os.getenv("AZURE_SPEECH_REGION"):
        return "azure"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None


def synthesize_speech(text: str, language: str = "en-US") -> bytes | None:
    cleaned = text.strip()
    provider = tts_provider()
    if not cleaned or not provider:
        return None
    return _synthesize_cached(cleaned, language_family(language), provider)


@lru_cache(maxsize=32)
def _synthesize_cached(text: str, family: str, provider: str) -> bytes | None:
    if provider == "azure":
        audio = _azure_speech(text, family)
        if audio:
            return audio
    if provider in {"azure", "openai"} or os.getenv("OPENAI_API_KEY"):
        return _openai_speech(text, family)
    return None


def _azure_speech(text: str, family: str) -> bytes | None:
    key = os.getenv("AZURE_SPEECH_KEY")
    region = os.getenv("AZURE_SPEECH_REGION")
    if not key or not region:
        return None
    locale = "vi-VN" if family == "vi" else "en-US"
    voice = AZURE_VOICE[family]
    ssml = (
        f"<speak version='1.0' xml:lang='{locale}'>"
        f"<voice name='{voice}'>"
        f"<prosody rate='-8%'>{xml.escape(text)}</prosody>"
        "</voice></speak>"
    )
    try:
        response = httpx.post(
            f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                "User-Agent": "guardian",
            },
            content=ssml.encode("utf-8"),
            timeout=20.0,
        )
        if response.status_code >= 400 or not response.content:
            return None
        return response.content
    except Exception:
        return None


def _openai_speech(text: str, family: str) -> bytes | None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    try:
        response = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.getenv("OPENAI_TTS_MODEL", "tts-1-hd"),
                "voice": OPENAI_VOICE[family],
                "input": text,
                "speed": 0.92,
            },
            timeout=20.0,
        )
        if response.status_code >= 400 or not response.content:
            return None
        return response.content
    except Exception:
        return None
