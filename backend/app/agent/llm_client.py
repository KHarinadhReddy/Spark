from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ..config import Settings

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Used when the primary Gemini model runs out of quota / degrades.
GEMINI_FALLBACK_MODEL = "gemini-3.1-flash-lite-preview"


class LLMError(Exception):
    pass


class LLMClient:
    """Free-first LLM adapter.

    Gemini and Groq are supported through a small JSON protocol so the same
    planner works on both. The model never executes tools itself: it returns
    ``tool_calls`` and the backend runs them through the approval gate.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = settings.llm_provider
        entries: list[tuple[str, str]] = []
        if settings.gemini_api_key:
            entries.append(("gemini", settings.gemini_model))
            entries.append(("gemini", GEMINI_FALLBACK_MODEL))
        if settings.groq_api_key:
            entries.append(("groq", settings.groq_model))
        self.providers = entries
        primary = (
            settings.llm_provider if any(p == settings.llm_provider for p, _ in entries) else (entries[0][0] if entries else settings.llm_provider)
        )
        self.provider = primary
        self.model = next((m for p, m in entries if p == primary), entries[0][1] if entries else settings.gemini_model)

    @property
    def configured(self) -> bool:
        return bool(self.providers)

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "configured": self.configured,
            "fallbacks": [f for f in self.providers if f != (self.provider, self.model)],
        }

    # --------------------------------------------------------------- public API
    def complete_json(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        schema_hint: str = "",
        temperature: float = 0.2,
        max_tokens: int = 1400,
    ) -> dict[str, Any] | None:
        if not self.configured:
            return None
        prompt = system
        if schema_hint:
            prompt += (
                "\n\nReturn ONLY valid JSON. No markdown fences, no commentary. "
                f"Shape: {schema_hint}"
            )
        for provider, model in self.providers:
            try:
                if provider == "gemini":
                    text = self._gemini(prompt, messages, temperature, max_tokens, json_mode=True, model=model)
                else:
                    text = self._groq(prompt, messages, temperature, max_tokens, json_mode=True, model=model)
            except Exception:
                continue
            parsed = _parse_json(text)
            if parsed is not None:
                return parsed
        return None

    def complete_text(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.4,
        max_tokens: int = 700,
    ) -> str | None:
        if not self.configured:
            return None
        for provider, model in self.providers:
            try:
                if provider == "gemini":
                    text = self._gemini(system, messages, temperature, max_tokens, json_mode=False, model=model)
                else:
                    text = self._groq(system, messages, temperature, max_tokens, json_mode=False, model=model)
            except Exception:
                continue
            if text.strip():
                return text
        return None

    # ---------------------------------------------------------------- providers
    def _gemini(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        *,
        json_mode: bool,
        model: str | None = None,
    ) -> str:
        contents = []
        for message in messages:
            role = "model" if message.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.get("content", "")}]})
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        url = GEMINI_URL.format(model=model or self.model)
        data = self._post(
            url,
            headers={"content-type": "application/json"},
            params={"key": self.settings.gemini_api_key},
            payload=payload,
            timeout=60,
        )
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(str(data.get("promptFeedback", "no candidate")))
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts).strip()

    def _groq(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        *,
        json_mode: bool,
        model: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post(
            GROQ_URL,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.settings.groq_api_key}",
            },
            payload=payload,
            timeout=60,
        )
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("no choices")
        return (choices[0].get("message", {}).get("content") or "").strip()

    @staticmethod
    def _post(
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: int = 60,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, headers=headers, json=payload, params=params)
                if response.status_code == 429:
                    # Quota exhausted — do not waste time retrying; fall through to the next provider/model.
                    last_error = LLMError(f"LLM {response.status_code}: {response.text[:200]}")
                    break
                if response.status_code in {500, 502, 503, 504}:
                    backoff = 2.0 * (2 ** attempt) + 1.0
                    time.sleep(backoff)
                    last_error = LLMError(f"LLM {response.status_code}: {response.text[:200]}")
                    continue
                if response.status_code >= 400:
                    raise LLMError(f"LLM {response.status_code}: {response.text[:200]}")
                return response.json()
            except Exception as exc:  # retry with backoff on transport errors
                last_error = exc
                time.sleep(2.0 * (2 ** attempt) + 1.0)
        raise LLMError(str(last_error) if last_error else "LLM request failed")


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except Exception:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(cleaned[start : end + 1])
            return value if isinstance(value, dict) else None
        except Exception:
            return None
    return None
