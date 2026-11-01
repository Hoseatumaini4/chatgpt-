# SMS ↔ Gemini gateway (Africa's Talking)

Text a number → Africa's Talking calls your webhook → Gemini answers → reply comes back by SMS.
(ChatGPT/OpenAI is optional: add `OPENAI_API_KEY` and users can text `GPT`. Without it, Gemini only.)

```
Phone ──SMS──> Africa's Talking ──POST /sms/incoming?token=…──> this app ──> Gemini
Phone <──SMS── Africa's Talking <──────────── send reply ──────────────┘
```

## 1. Keys you need
| What | Where |
|---|---|
| Africa's Talking API key + username | account.africastalking.com → Settings → API Key (sandbox app uses username `sandbox`) |
| Gemini API key | aistudio.google.com → Get API key |

## 2. Run locally (no cost, no SMS sent)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill GEMINI_API_KEY, WEBHOOK_TOKEN; set DRY_RUN=1
pytest                      # 14 tests should pass
gunicorn wsgi:app -b 127.0.0.1:8000
# other terminal:
python scripts/simulate.py "Malaria ni nini?"    # reply is printed in the server log
```

## 3. Receive real SMS
1. Receiving needs a **shortcode or long number** on your Africa's Talking account (Sandbox: SMS → Shortcodes; Live: request one for Tanzania — it is not free and takes approval time). Menu names may differ slightly.
2. Put the app online over HTTPS (Render, Railway, Fly.io, a VPS, or Docker). Use **one always-on server**, not serverless: replies are sent from a background thread. For a quick test: `ngrok http 8000`.
3. In Africa's Talking: SMS → SMS Callback URLs → **Incoming Messages** →
   `https://YOUR-HOST/sms/incoming?token=YOUR_WEBHOOK_TOKEN`
4. Sandbox: use the simulator (Launch Simulator) to send an SMS to your shortcode. For live: set `AT_SANDBOX=false`, `AT_USERNAME=<your app username>`, live `AT_API_KEY`, and have SMS balance.

Africa's Talking does not sign callbacks, so the secret `token` in the URL is your only guard. Keep it long and private.

## 4. User commands (by SMS)
`HELP`/`MSAADA` · `RESET`/`FUTA` (clear memory) · `GPT` · `GEMINI`

## 5. Protect your money
Every reply is a billed SMS. Built in: `ALLOWED_NUMBERS` (silent for others), `DAILY_LIMIT_PER_NUMBER` (default 20, one notice then quiet), replies capped at 459 chars (3 segments), emoji/markdown stripped so messages stay 160-char GSM-7 segments, duplicate callbacks ignored. **Set `ALLOWED_NUMBERS` to your own number while testing.**

## 6. Settings (`.env`)
See `.env.example`. Key ones: `GEMINI_MODEL` (verify the name is current in AI Studio; change it if Google retires it), `SYSTEM_PROMPT` (override tone/language), `HISTORY_MESSAGES`/`HISTORY_TTL_MINUTES` (conversation memory), `DB_PATH` (SQLite; mount a volume in Docker/Render so memory survives restarts).

## 7. Deploy
- **Render/Railway**: new web service from this folder, start command from `Procfile`, add env vars in the dashboard.
- **Docker**: `docker build -t sms-ai . && docker run -p 8000:8000 -v sms-data:/data --env-file .env sms-ai`
- Check `https://YOUR-HOST/health`.
Keep `--workers 1` (the in-memory executor and SQLite are per process).

## Files
`gateway/` app code · `tests/` · `scripts/simulate.py` · `wsgi.py` · `Procfile` · `Dockerfile`

## Deploy on Vercel (no background thread, no persistent disk)
1. Push this folder to GitHub (`.env` is git-ignored) and import it in Vercel, or run `vercel` in the folder.
2. Project → Settings → **Environment Variables**: add `AT_USERNAME`, `AT_API_KEY`, `AT_SANDBOX`, `GEMINI_API_KEY`, `WEBHOOK_TOKEN`, `ALLOWED_NUMBERS`. Redeploy after adding them.
3. Vercel is detected automatically: replies are sent inside the request (`SYNC_MODE`) and the SQLite file lives in `/tmp`.
4. Limits: `/tmp` is not shared between instances and is wiped on cold starts, so conversation memory, the daily limit and duplicate-callback protection are only best-effort. For hard limits use Render/Railway instead.
5. Check `https://YOUR-APP.vercel.app/health`.
