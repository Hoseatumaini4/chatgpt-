from concurrent.futures import Executor, Future

import pytest

from gateway.ai import AIError, AIRouter
from gateway.app import create_app
from gateway.config import Config, ConfigError, normalize_phone
from gateway.sms import AfricasTalking, SmsError
from gateway.text import to_sms_text

BASE = {"AT_API_KEY": "k", "GEMINI_API_KEY": "g", "WEBHOOK_TOKEN": "tok"}


def cfg(tmp_path, **extra):
    env = dict(BASE, DB_PATH=str(tmp_path / "t.db"), **extra)
    return Config.from_env(env)


class SyncExecutor(Executor):
    def submit(self, fn, *a, **k):
        f = Future(); f.set_result(fn(*a, **k)); return f


class FakeSMS:
    def __init__(self): self.sent = []
    def send(self, to, message): self.sent.append((to, message))


class FakeAI:
    def __init__(self, reply="**Hello** 😀 world", fail=False):
        self.reply, self.fail, self.calls = reply, fail, []
    def available(self): return ["gemini", "openai"]
    def ask(self, preferred, history):
        self.calls.append((preferred, list(history)))
        if self.fail: raise AIError("down")
        return preferred, self.reply


class Resp:
    def __init__(self, status=200, body=None): self.status_code, self._b, self.text = status, body, str(body)
    def json(self):
        if self._b is None: raise ValueError
        return self._b


class Sess:
    def __init__(self, resp): self.resp, self.last = resp, None
    def post(self, url, **kw): self.last = (url, kw); return self.resp


def client(tmp_path, ai=None, **extra):
    sms = FakeSMS(); ai = ai or FakeAI()
    app = create_app(cfg(tmp_path, **extra), sms=sms, ai=ai, executor=SyncExecutor())
    return app.test_client(), sms, ai


# ---- config / text
def test_phone():
    assert normalize_phone("00255 712-345-678") == "+255712345678"
    assert normalize_phone("255712345678") == "+255712345678"

def test_config_requires_token_and_keys():
    with pytest.raises(ConfigError): Config.from_env({"AT_API_KEY": "k", "GEMINI_API_KEY": "g"})
    with pytest.raises(ConfigError): Config.from_env({"WEBHOOK_TOKEN": "t"})

def test_text_clean_and_cap():
    out = to_sms_text("**Bold** “quote” 😀 – hi\n\n- item")
    assert out.isascii() and "*" not in out and "😀" not in out
    assert len(to_sms_text("word " * 500, 459)) <= 459


# ---- sms client
def test_sms_ok_and_reject():
    ok = {"SMSMessageData": {"Recipients": [{"statusCode": 101, "number": "+255"}]}}
    s = Sess(Resp(201, ok)); at = AfricasTalking("sandbox", "key", "SENDER", True, session=s)
    at.send("+255", "hi")
    assert "sandbox" in s.last[0] and s.last[1]["headers"]["apiKey"] == "key" and s.last[1]["data"]["from"] == "SENDER"
    bad = {"SMSMessageData": {"Recipients": [{"statusCode": 405, "status": "InsufficientBalance", "number": "+255"}]}}
    with pytest.raises(SmsError): AfricasTalking("u", "k", session=Sess(Resp(201, bad))).send("+255", "hi")
    with pytest.raises(SmsError): AfricasTalking("u", "k", session=Sess(Resp(401, {}))).send("+255", "hi")


# ---- ai
def test_gemini_parse_and_fallback(tmp_path):
    c = cfg(tmp_path, OPENAI_API_KEY="o")
    body = {"candidates": [{"content": {"parts": [{"text": "Habari"}]}}]}
    s = Sess(Resp(200, body)); r = AIRouter(c, session=s)
    assert r.ask("gemini", [{"role": "user", "content": "hi"}]) == ("gemini", "Habari")
    assert s.last[1]["headers"]["x-goog-api-key"] == "g"

    class Two:
        n = 0
        def post(self, url, **kw):
            Two.n += 1
            if "googleapis" in url: return Resp(500, {"e": 1})
            return Resp(200, {"choices": [{"message": {"content": "from gpt"}}]})
    assert AIRouter(c, session=Two()).ask("gemini", [{"role": "user", "content": "x"}]) == ("openai", "from gpt")

def test_ai_all_fail(tmp_path):
    with pytest.raises(AIError): AIRouter(cfg(tmp_path), session=Sess(Resp(500, {}))).ask("gemini", [])


# ---- webhook end to end
def post(c, text, sender="+255712345678", mid="1", token="tok"):
    return c.post(f"/sms/incoming?token={token}", data={"from": sender, "text": text, "id": mid})

def test_bad_token(tmp_path):
    c, sms, _ = client(tmp_path)
    assert post(c, "hi", token="nope").status_code == 403 and not sms.sent

def test_answer_sanitised(tmp_path):
    c, sms, ai = client(tmp_path)
    assert post(c, "hello").status_code == 200
    assert sms.sent == [("+255712345678", "Hello world")]

def test_dedupe_and_memory_and_reset(tmp_path):
    c, sms, ai = client(tmp_path)
    post(c, "one", mid="a"); post(c, "one", mid="a"); post(c, "two", mid="b")
    assert len(sms.sent) == 2
    assert [m["content"] for m in ai.calls[-1][1]][0] == "one"
    post(c, "reset", mid="c")
    post(c, "three", mid="d")
    assert len(ai.calls[-1][1]) == 1

def test_allowed_numbers_silent(tmp_path):
    c, sms, _ = client(tmp_path, ALLOWED_NUMBERS="+255700000001")
    post(c, "hi"); assert not sms.sent

def test_daily_limit_notice_once(tmp_path):
    c, sms, ai = client(tmp_path, DAILY_LIMIT_PER_NUMBER="2")
    for i in range(5): post(c, f"q{i}", mid=str(i))
    assert len(ai.calls) == 2 and len(sms.sent) == 3  # 2 answers + one limit notice

def test_ai_failure_sends_apology(tmp_path):
    c, sms, _ = client(tmp_path, ai=FakeAI(fail=True))
    post(c, "hi"); assert "Samahani" in sms.sent[0][1]

def test_commands(tmp_path):
    c, sms, ai = client(tmp_path)
    post(c, "help", mid="1"); post(c, "gpt", mid="2"); post(c, "hi", mid="3")
    assert "RESET" in sms.sent[0][1] and ai.calls[-1][0] == "openai"

def test_health(tmp_path):
    c, *_ = client(tmp_path); assert c.get("/health").json["status"] == "ok"


def test_sync_mode_answers_inside_request(tmp_path):
    sms = FakeSMS()
    class Boom(Executor):
        def submit(self, *a, **k): raise AssertionError("executor must not be used")
    app = create_app(cfg(tmp_path, SYNC_MODE="1"), sms=sms, ai=FakeAI("ok"), executor=Boom())
    r = app.test_client().post("/sms/incoming?token=tok", data={"from": "+255712345678", "text": "hi", "id": "z"})
    assert r.status_code == 200 and sms.sent == [("+255712345678", "ok")]

def test_vercel_defaults(tmp_path):
    c = Config.from_env(dict(BASE, VERCEL="1"))
    assert c.sync_mode and c.db_path == "/tmp/gateway.db"
