"""Minimal Africa's Talking SMS client (plain HTTPS, no SDK needed)."""
from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

LIVE_URL = "https://api.africastalking.com/version1/messaging"
SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"
OK_STATUS_CODES = {100, 101, 102}  # Processed / Sent / Queued


class SmsError(RuntimeError):
    pass


class AfricasTalking:
    def __init__(self, username: str, api_key: str, sender_id: str = "", sandbox: bool = True,
                 session: Optional[requests.Session] = None, timeout: int = 15, dry_run: bool = False):
        self.username = username
        self.api_key = api_key
        self.sender_id = sender_id
        self.url = SANDBOX_URL if sandbox else LIVE_URL
        self.session = session or requests.Session()
        self.timeout = timeout
        self.dry_run = dry_run

    def send(self, to: str, message: str) -> dict:
        if self.dry_run:
            log.info("DRY_RUN sms to %s: %s", to, message)
            return {"dry_run": True}
        data = {"username": self.username, "to": to, "message": message}
        if self.sender_id:
            data["from"] = self.sender_id
        try:
            resp = self.session.post(
                self.url,
                data=data,
                headers={"apiKey": self.api_key, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SmsError(f"Could not reach Africa's Talking: {exc}") from exc
        if resp.status_code >= 400:
            raise SmsError(f"Africa's Talking returned HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
            recipients = body["SMSMessageData"]["Recipients"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SmsError(f"Unexpected Africa's Talking response: {resp.text[:200]}") from exc
        if not recipients:
            raise SmsError(f"Africa's Talking accepted no recipients: {body['SMSMessageData'].get('Message')}")
        bad = [r for r in recipients if r.get("statusCode") not in OK_STATUS_CODES]
        if bad:
            raise SmsError(f"SMS rejected for {bad[0].get('number')}: {bad[0].get('status')}")
        return body
