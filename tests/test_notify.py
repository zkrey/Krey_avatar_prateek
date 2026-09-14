"""Deterministic verification of the optional email notifier (no network — SMTP patched)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import notify

TICKET = {"severity": "high", "kind": "functional", "route": "standard",
          "screen": "alpha-twin-check", "device_specific": False, "dedup_key": "abc123",
          "note": "• Eye colour: shown Brown → should be green"}

ENV_KEYS = ["KREY_SMTP_HOST", "KREY_SMTP_PORT", "KREY_SMTP_USER", "KREY_SMTP_PASS",
            "KREY_FEEDBACK_EMAIL_TO", "KREY_FEEDBACK_EMAIL_FROM"]


def _clear(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def _configure(monkeypatch, port="587"):
    monkeypatch.setenv("KREY_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("KREY_SMTP_PORT", port)
    monkeypatch.setenv("KREY_SMTP_USER", "krey@example.com")
    monkeypatch.setenv("KREY_SMTP_PASS", "app-password")
    monkeypatch.setenv("KREY_FEEDBACK_EMAIL_TO", "team@example.com")


def test_unconfigured_is_noop(monkeypatch):
    _clear(monkeypatch)
    assert notify.smtp_configured() is False
    assert notify.send_feedback_email(TICKET) is False   # no-op, no crash


def test_build_message_carries_note_and_headers(monkeypatch):
    _clear(monkeypatch); _configure(monkeypatch)
    msg = notify.build_message(TICKET)
    assert msg["To"] == "team@example.com"
    assert msg["From"] == "krey@example.com"             # defaults to SMTP user
    assert msg["Subject"].startswith("Krey alpha feedback")
    # severity in the subject; a note snippet replaces the (constant) dedup when present
    assert "high" in msg["Subject"] and "green" in msg["Subject"]
    body = msg.get_content()
    assert "should be green" in body and "severity : high" in body


class _FakeSMTP:
    sent = []
    def __init__(self, host, port, timeout=None): _FakeSMTP.host, _FakeSMTP.port = host, port
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def ehlo(self): pass
    def starttls(self, context=None): _FakeSMTP.tls = True
    def login(self, u, p): _FakeSMTP.creds = (u, p)
    def send_message(self, msg): _FakeSMTP.sent.append(msg)


def test_send_uses_starttls_on_587(monkeypatch):
    _clear(monkeypatch); _configure(monkeypatch, port="587")
    _FakeSMTP.sent = []; _FakeSMTP.tls = False
    monkeypatch.setattr(notify.smtplib, "SMTP", _FakeSMTP)
    ok = notify.send_feedback_email(TICKET)
    assert ok is True
    assert _FakeSMTP.tls is True                          # STARTTLS was used
    assert _FakeSMTP.creds == ("krey@example.com", "app-password")
    assert len(_FakeSMTP.sent) == 1
    assert "green" in _FakeSMTP.sent[0].get_content()


def test_send_swallows_errors(monkeypatch):
    _clear(monkeypatch); _configure(monkeypatch)
    def boom(*a, **k): raise OSError("smtp down")
    monkeypatch.setattr(notify.smtplib, "SMTP", boom)
    assert notify.send_feedback_email(TICKET) is False    # never raises


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
