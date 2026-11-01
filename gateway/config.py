"""Configuration, read once from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

DEFAULT_SYSTEM_PROMPT = (
    "You are an assistant that talks to people by SMS. "
    "Reply in the same language the user writes in (Swahili or English). "
    "Keep every answer under 300 characters. Plain text only: no markdown, "
    "no emojis, no bullet symbols. If a full answer would be long, give the most "
    "useful short version and tell the user they can ask for more."
)


class ConfigError(RuntimeError):
    """Raised at startup when required settings are missing."""


def _bool(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: Optional[str]) -> tuple:
    return tuple(x.strip() for x in (value or "").split(",") if x.strip())


def normalize_phone(raw: str) -> str:
    """'+255 712-345-678' / '00255712345678' / '255712345678' -> '+255712345678'."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if not digits:
        return ""
    if (raw or "").strip().startswith("00"):
        digits = digits[2:]
    return "+" + digits


@dataclass(frozen=True)
class Config:
    # Africa's Talking
    at_username: str
    at_api_key: str
    at_sender_id: str
    at_sandbox: bool
    # AI providers
    ai_provider: str
    openai_api_key: str
    openai_model: str
    gemini_api_key: str
    gemini_model: str
    ai_timeout: int
    system_prompt: str
    # behaviour
    webhook_token: str
    allowed_numbers: tuple
    daily_limit: int
    max_reply_chars: int
    history_messages: int
    history_ttl_minutes: int
    db_path: str
    dry_run: bool
    sync_mode: bool = False

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        e = os.environ if env is None else env
        cfg = cls(
            at_username=e.get("AT_USERNAME", "sandbox"),
            at_api_key=e.get("AT_API_KEY", ""),
            at_sender_id=e.get("AT_SENDER_ID", ""),
            at_sandbox=_bool(e.get("AT_SANDBOX"), True),
            ai_provider=e.get("AI_PROVIDER", "gemini").strip().lower(),
            openai_api_key=e.get("OPENAI_API_KEY", ""),
            openai_model=e.get("OPENAI_MODEL", "gpt-4o-mini"),
            gemini_api_key=e.get("GEMINI_API_KEY", ""),
            gemini_model=e.get("GEMINI_MODEL", "gemini-2.5-flash"),
            ai_timeout=int(e.get("AI_TIMEOUT_SECONDS", "25")),
            system_prompt=e.get("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
            webhook_token=e.get("WEBHOOK_TOKEN", ""),
            allowed_numbers=tuple(normalize_phone(n) for n in _csv(e.get("ALLOWED_NUMBERS"))),
            daily_limit=int(e.get("DAILY_LIMIT_PER_NUMBER", "20")),
            max_reply_chars=int(e.get("MAX_REPLY_CHARS", "459")),
            history_messages=int(e.get("HISTORY_MESSAGES", "8")),
            history_ttl_minutes=int(e.get("HISTORY_TTL_MINUTES", "120")),
            db_path=e.get("DB_PATH", "/tmp/gateway.db" if e.get("VERCEL") else "gateway.db"),
            dry_run=_bool(e.get("DRY_RUN"), False),
            sync_mode=_bool(e.get("SYNC_MODE"), bool(e.get("VERCEL"))),
        )
        cfg.validate(allow_insecure=_bool(e.get("ALLOW_INSECURE_WEBHOOK"), False))
        return cfg

    def validate(self, allow_insecure: bool = False) -> None:
        problems = []
        if self.ai_provider not in {"openai", "gemini"}:
            problems.append("AI_PROVIDER must be 'openai' or 'gemini'.")
        if not (self.openai_api_key or self.gemini_api_key):
            problems.append("Set OPENAI_API_KEY and/or GEMINI_API_KEY.")
        if self.ai_provider == "openai" and not self.openai_api_key and self.gemini_api_key:
            pass  # router falls back to Gemini
        if not self.dry_run and not self.at_api_key:
            problems.append("Set AT_API_KEY (or DRY_RUN=1 to test without sending SMS).")
        if not self.webhook_token and not allow_insecure:
            problems.append(
                "Set WEBHOOK_TOKEN (any long random string) so strangers cannot trigger "
                "paid AI calls and SMS. For local experiments only: ALLOW_INSECURE_WEBHOOK=1."
            )
        if problems:
            raise ConfigError("Configuration problems:\n - " + "\n - ".join(problems))

    def providers_available(self) -> list:
        out = []
        if self.openai_api_key:
            out.append("openai")
        if self.gemini_api_key:
            out.append("gemini")
        return out
