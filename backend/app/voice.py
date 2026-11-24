from __future__ import annotations

import httpx

from .config import Settings


class VoiceNotConfigured(Exception):
    pass


class VoiceError(Exception):
    pass


class ElevenLabsVoice:
    """Thin ElevenLabs STT/TTS client. The browser voice is the always-available fallback."""

    BASE = "https://api.elevenlabs.io/v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.elevenlabs_api_key)

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise VoiceNotConfigured("ElevenLabs is not configured")
        return {"xi-api-key": self.settings.elevenlabs_api_key}

    def tts(self, text: str, language: str = "en") -> bytes:
        headers = {**self._headers(), "accept": "audio/mpeg"}
        payload = {
            "text": text[:2500],
            "model_id": self.settings.elevenlabs_tts_model,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.2},
        }
        with httpx.Client(timeout=40) as client:
            response = client.post(
                f"{self.BASE}/text-to-speech/{self.settings.elevenlabs_voice_id}",
                headers=headers,
                json=payload,
            )
        if response.status_code >= 400:
            raise VoiceError(f"ElevenLabs TTS {response.status_code}: {response.text[:200]}")
        return response.content

    def stt(self, audio: bytes, content_type: str = "audio/webm") -> str:
        headers = self._headers()
        extension = "webm"
        if "wav" in content_type:
            extension = "wav"
        elif "mp4" in content_type or "m4a" in content_type:
            extension = "m4a"
        elif "ogg" in content_type:
            extension = "ogg"
        files = {"file": (f"speech.{extension}", audio, content_type or "audio/webm")}
        data = {"model_id": self.settings.elevenlabs_stt_model}
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{self.BASE}/speech-to-text", headers=headers, files=files, data=data
            )
        if response.status_code >= 400:
            raise VoiceError(f"ElevenLabs STT {response.status_code}: {response.text[:200]}")
        return response.json().get("text", "").strip()
