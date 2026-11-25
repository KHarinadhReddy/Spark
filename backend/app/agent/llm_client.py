from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ..config import Settings

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


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
        self.providers = [
            provider
            for provider, key in (
                ("gemini", settings.gemini_api_key),
                ("groq", settings.groq_api_key),
            )
            if key
        ]
        if self.provider in self.providers:
            self.providers.remove(self.provider)
            self.providers.insert(0, self.provider)
        self.model = (
            settings.gemini_model
            if self.providers and self.providers[0] == "gemini"
            else settings.groq_model
        )

    @property
    def configured(self) -> bool:
        return bool(self.providers)

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "configured": self.configured,
            "fallbacks": self.providers[1:],
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
        for provider in self.providers:
            try:
                if provider == "gemini":
                    text = self._gemini(prompt, messages, temperature, max_tokens, json_mode=True)
                else:
                    text = self._groq(prompt, messages, temperature, max_tokens, json_mode=True)
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
        for provider in self.providers:
            try:
                if provider == "gemini":
                    text = self._gemini(system, messages, temperature, max_tokens, json_mode=False)
                else:
                    text = self._groq(system, messages, temperature, max_tokens, json_mode=False)
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
        url = GEMINI_URL.format(model=self.settings.gemini_model)
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
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.settings.groq_model,
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
        for attempt in range(2):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, headers=headers, json=payload, params=params)
                if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                    time.sleep(1.5)
                    continue
                if response.status_code >= 400:
                    raise LLMError(f"LLM {response.status_code}: {response.text[:200]}")
                return response.json()
            except Exception as exc:  # retry once on transport errors
                last_error = exc
                if attempt == 0:
                    time.sleep(1.0)
                    continue
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
