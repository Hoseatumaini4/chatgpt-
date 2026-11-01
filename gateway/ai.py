"""OpenAI and Gemini over plain HTTPS, behind one router with automatic fallback."""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import requests

from .config import Config

log = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class AIError(RuntimeError):
    pass


class AIRouter:
    def __init__(self, cfg: Config, session: Optional[requests.Session] = None):
        self.cfg = cfg
        self.session = session or requests.Session()

    def available(self) -> List[str]:
        return self.cfg.providers_available()

    def ask(self, preferred: str, history: List[dict]) -> Tuple[str, str]:
        """Return (provider_used, reply). Falls back to the other provider on failure."""
        available = self.available()
        order = [p for p in [preferred] + available if p in available]
        order = list(dict.fromkeys(order))
        if not order:
            raise AIError("No AI provider is configured.")
        last: Optional[Exception] = None
        for provider in order:
            try:
                reply = self._call(provider, history)
                if reply.strip():
                    return provider, reply.strip()
                raise AIError(f"{provider} returned an empty reply")
            except AIError as exc:
                log.warning("AI provider %s failed: %s", provider, exc)
                last = exc
        raise AIError(str(last))

    def _call(self, provider: str, history: List[dict]) -> str:
        return self._openai(history) if provider == "openai" else self._gemini(history)

    def _post(self, url: str, headers: dict, payload: dict, label: str) -> dict:
        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=self.cfg.ai_timeout)
        except requests.RequestException as exc:
            raise AIError(f"{label} unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise AIError(f"{label} HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AIError(f"{label} returned invalid JSON") from exc

    def _openai(self, history: List[dict]) -> str:
        payload = {
            "model": self.cfg.openai_model,
            "messages": [{"role": "system", "content": self.cfg.system_prompt}] + history,
            "max_completion_tokens": 400,
        }
        data = self._post(
            OPENAI_URL,
            {"Authorization": f"Bearer {self.cfg.openai_api_key}", "Content-Type": "application/json"},
            payload,
            "OpenAI",
        )
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"OpenAI response had no text: {str(data)[:200]}") from exc

    def _gemini(self, history: List[dict]) -> str:
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in history
        ]
        payload = {
            "systemInstruction": {"parts": [{"text": self.cfg.system_prompt}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 1024},
        }
        data = self._post(
            GEMINI_URL.format(model=self.cfg.gemini_model),
            {"x-goog-api-key": self.cfg.gemini_api_key, "Content-Type": "application/json"},
            payload,
            "Gemini",
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            reason = data.get("promptFeedback") or data.get("candidates")
            raise AIError(f"Gemini response had no text: {str(reason)[:200]}") from exc
