"""Flask app: the webhook Africa's Talking calls for every incoming SMS."""
from __future__ import annotations

import hmac
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from flask import Flask, abort, jsonify, request

from .ai import AIRouter
from .config import Config
from .service import Gateway
from .sms import AfricasTalking
from .store import Store

log = logging.getLogger(__name__)


def create_app(cfg: Optional[Config] = None, *, sms=None, ai=None, executor=None) -> Flask:
    cfg = cfg or Config.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    store = Store(cfg.db_path)
    store.purge()
    sms = sms or AfricasTalking(
        cfg.at_username, cfg.at_api_key, cfg.at_sender_id, cfg.at_sandbox, dry_run=cfg.dry_run
    )
    ai = ai or AIRouter(cfg)
    # Africa's Talking expects a quick HTTP 200, but an AI call can take many seconds,
    # so the webhook acknowledges immediately and the work happens on a background thread.
    executor = executor or ThreadPoolExecutor(max_workers=4)
    gateway = Gateway(cfg, store, sms, ai)

    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(status="ok", providers=cfg.providers_available(), sandbox=cfg.at_sandbox, dry_run=cfg.dry_run)

    @app.post("/sms/incoming")
    def incoming():
        if cfg.webhook_token and not hmac.compare_digest(request.args.get("token", ""), cfg.webhook_token):
            abort(403)
        sender = request.form.get("from", "").strip()
        text = request.form.get("text", "").strip()
        msg_id = request.form.get("id", "").strip()
        if sender and text:
            if cfg.sync_mode:  # serverless (Vercel): the function is frozen after responding, so finish first
                gateway.handle(sender, text, msg_id)
            else:
                executor.submit(gateway.handle, sender, text, msg_id)
        return "", 200

    return app
