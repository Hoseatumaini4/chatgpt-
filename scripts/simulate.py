"""Pretend to be Africa's Talking: POST an incoming SMS to your local webhook.

    python scripts/simulate.py "What is malaria?" --from +255712345678
Run the server first with DRY_RUN=1 so replies are printed in its log instead of sent.
"""
import argparse, os, sys, time
import requests

p = argparse.ArgumentParser()
p.add_argument("text")
p.add_argument("--from", dest="sender", default="+255712345678")
p.add_argument("--url", default="http://127.0.0.1:8000/sms/incoming")
p.add_argument("--token", default=os.environ.get("WEBHOOK_TOKEN", ""))
a = p.parse_args()
r = requests.post(
    a.url, params={"token": a.token},
    data={"from": a.sender, "to": "20880", "text": a.text, "id": f"sim-{time.time_ns()}",
          "date": time.strftime("%Y-%m-%d %H:%M:%S"), "linkId": "sim"},
    timeout=10,
)
print("HTTP", r.status_code)
sys.exit(0 if r.ok else 1)
