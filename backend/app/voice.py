from __future__ import annotations

import asyncio
import io
from typing import Any

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


class EdgeTTS:
    """Free neural voices via Microsoft Edge's TTS endpoint.

    This is a free fallback, not the proprietary ElevenLabs voice. It supports
    Indian English and Hindi and works without an API key.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.edge_tts_enabled)

    def tts(self, text: str, language: str = "en") -> bytes:
        if not self.configured:
            raise VoiceNotConfigured("Edge TTS is disabled")
        try:
            import edge_tts
        except Exception as exc:
            raise VoiceNotConfigured("edge-tts package is not installed") from exc
        voice = (
            self.settings.edge_tts_voice_hi
            if language == "hi"
            else self.settings.edge_tts_voice_en
        )
        communicate = edge_tts.Communicate(text[:5000], voice)
        buffer = io.BytesIO()

        async def collect() -> None:
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    buffer.write(chunk.get("data", b""))

        try:
            asyncio.run(collect())
        except RuntimeError:
            # An event loop is already running (e.g. from an async caller).
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(collect())
            finally:
                loop.close()
        except Exception as exc:
            raise VoiceError(f"Edge TTS failed: {exc}") from exc
        data = buffer.getvalue()
        if not data:
            raise VoiceError("Edge TTS returned no audio")
        return data


class GroqWhisper:
    """Free-tier Whisper transcription through Groq's OpenAI-compatible API."""

    URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.groq_api_key)

    def stt(self, audio: bytes, content_type: str = "audio/webm", language: str = "") -> str:
        if not self.configured:
            raise VoiceNotConfigured("Groq is not configured")
        extension = "webm"
        if "wav" in content_type:
            extension = "wav"
        elif "mp4" in content_type or "m4a" in content_type:
            extension = "m4a"
        elif "ogg" in content_type:
            extension = "ogg"
        data: dict[str, Any] = {
            "model": self.settings.groq_whisper_model,
            "response_format": "json",
        }
        if language in {"en", "hi"}:
            data["language"] = language
        files = {"file": (f"speech.{extension}", audio, content_type or "audio/webm")}
        with httpx.Client(timeout=90) as client:
            response = client.post(
                self.URL,
                headers={"authorization": f"Bearer {self.settings.groq_api_key}"},
                data=data,
                files=files,
            )
        if response.status_code >= 400:
            raise VoiceError(f"Groq STT {response.status_code}: {response.text[:200]}")
        return (response.json().get("text") or "").strip()


class VoiceService:
    """Provider chain: premium ElevenLabs, free Edge/Groq, then browser fallback."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.eleven = ElevenLabsVoice(settings)
        self.edge = EdgeTTS(settings)
        self.groq = GroqWhisper(settings)

    @property
    def tts_available(self) -> bool:
        return self.eleven.configured or self.edge.configured

    @property
    def stt_available(self) -> bool:
        return self.eleven.configured or self.groq.configured

    def status(self) -> dict[str, Any]:
        return {
            "tts": (
                "elevenlabs"
                if self.eleven.configured
                else "edge-tts"
                if self.edge.configured
                else "browser"
            ),
            "stt": (
                "elevenlabs"
                if self.eleven.configured
                else "groq-whisper"
                if self.groq.configured
                else "browser"
            ),
            "tts_available": self.tts_available,
            "stt_available": self.stt_available,
        }

    def tts(self, text: str, language: str = "en") -> tuple[bytes, str]:
        errors: list[str] = []
        if self.eleven.configured:
            try:
                return self.eleven.tts(text, language), "audio/mpeg"
            except Exception as exc:
                errors.append(str(exc))
        if self.edge.configured:
            try:
                return self.edge.tts(text, language), "audio/mpeg"
            except Exception as exc:
                errors.append(str(exc))
        raise VoiceNotConfigured(
            "No server TTS provider is configured. Set ELEVENLABS_API_KEY or SPARK_EDGE_TTS=1."
            + (f" Last error: {errors[-1]}" if errors else "")
        )

    def stt(
        self,
        audio: bytes,
        content_type: str = "audio/webm",
        language: str = "",
    ) -> str:
        errors: list[str] = []
        if self.eleven.configured:
            try:
                return self.eleven.stt(audio, content_type)
            except Exception as exc:
                errors.append(str(exc))
        if self.groq.configured:
            try:
                return self.groq.stt(audio, content_type, language)
            except Exception as exc:
                errors.append(str(exc))
        raise VoiceNotConfigured(
            "No server STT provider is configured. Set ELEVENLABS_API_KEY or GROQ_API_KEY."
            + (f" Last error: {errors[-1]}" if errors else "")
        )
