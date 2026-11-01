"""The conversation logic: commands, limits, memory, AI call, SMS reply."""
from __future__ import annotations

import logging

from .ai import AIError, AIRouter
from .config import Config, normalize_phone
from .sms import AfricasTalking, SmsError
from .store import Store
from .text import to_sms_text

log = logging.getLogger(__name__)

HELP_TEXT = (
    "Uliza swali lolote kwa SMS. Maagizo: RESET = anza upya, GPT = tumia ChatGPT, "
    "GEMINI = tumia Gemini, HELP = msaada. Ask anything by SMS. Commands: RESET, GPT, GEMINI, HELP."
)
LIMIT_TEXT = "Umefikia kikomo cha ujumbe wa leo. Jaribu kesho. Daily message limit reached. Try tomorrow."
ERROR_TEXT = "Samahani, kuna tatizo la muda. Jaribu tena baadaye. Sorry, temporary problem. Please try again later."

COMMANDS = {
    "help": "help", "msaada": "help", "?": "help",
    "reset": "reset", "futa": "reset", "new": "reset",
    "gpt": "openai", "chatgpt": "openai", "openai": "openai", "use gpt": "openai",
    "gemini": "gemini", "use gemini": "gemini",
}


class Gateway:
    def __init__(self, cfg: Config, store: Store, sms: AfricasTalking, ai: AIRouter):
        self.cfg, self.store, self.sms, self.ai = cfg, store, sms, ai

    def handle(self, sender: str, text: str, msg_id: str = "") -> None:
        """Process one inbound SMS. Never raises: failures are logged (this runs in a background thread)."""
        try:
            self._handle(sender, text, msg_id)
        except Exception:  # noqa: BLE001 - last line of defence for a background thread
            log.exception("Unhandled error while processing SMS from %s", sender)

    # ------------------------------------------------------------------
    def _handle(self, sender: str, text: str, msg_id: str) -> None:
        phone = normalize_phone(sender)
        if not phone:
            return
        if self.cfg.allowed_numbers and phone not in self.cfg.allowed_numbers:
            log.info("Ignoring SMS from non-allowed number %s", phone)  # stay silent: replying costs money
            return
        if not self.store.claim_message(msg_id):
            log.info("Duplicate callback for message %s ignored", msg_id)
            return

        command = COMMANDS.get(" ".join(text.lower().split()))
        if command:
            self._run_command(phone, command)
            return

        used_today = self.store.bump_usage(phone)
        if used_today > self.cfg.daily_limit:
            if used_today == self.cfg.daily_limit + 1:  # tell them once, then go quiet
                self._reply(phone, LIMIT_TEXT)
            return

        self.store.add(phone, "user", text.strip())
        history = self.store.history(phone, self.cfg.history_messages, self.cfg.history_ttl_minutes)
        preferred = self.store.get_provider(phone) or self.cfg.ai_provider
        try:
            provider, answer = self.ai.ask(preferred, history)
        except AIError:
            log.exception("All AI providers failed for %s", phone)
            self._reply(phone, ERROR_TEXT)
            return
        reply = to_sms_text(answer, self.cfg.max_reply_chars)
        self.store.add(phone, "assistant", reply)
        log.info("Answered %s via %s (%d chars)", phone, provider, len(reply))
        self._reply(phone, reply)

    def _run_command(self, phone: str, command: str) -> None:
        if command == "help":
            self._reply(phone, HELP_TEXT)
        elif command == "reset":
            self.store.clear(phone)
            self._reply(phone, "Sawa, tumeanza upya. OK, conversation cleared.")
        else:  # openai | gemini
            if command not in self.ai.available():
                self._reply(phone, f"{command} haipatikani / is not configured on this server.")
                return
            self.store.set_provider(phone, command)
            label = "ChatGPT" if command == "openai" else "Gemini"
            self._reply(phone, f"Sawa, sasa nitatumia {label}. OK, now using {label}.")

    def _reply(self, phone: str, message: str) -> None:
        try:
            self.sms.send(phone, message)
        except SmsError:
            log.exception("Failed to send SMS to %s", phone)
