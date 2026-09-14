"""
Optional email notifier for alpha feedback — no third-party service, just SMTP.

Configured entirely by environment (never hard-code credentials):
  KREY_SMTP_HOST            e.g. smtp.gmail.com
  KREY_SMTP_PORT            default 587 (STARTTLS); 465 uses implicit SSL
  KREY_SMTP_USER            SMTP username (usually the from-address)
  KREY_SMTP_PASS            SMTP password / app-password (Gmail: an App Password)
  KREY_FEEDBACK_EMAIL_TO    where alpha feedback lands (comma-separated allowed)
  KREY_FEEDBACK_EMAIL_FROM  optional; defaults to KREY_SMTP_USER

When these aren't set, everything is a no-op and feedback still lands in the logs
(the pluggable analytics sink). Best-effort: sending never raises into the request.
Pure stdlib (smtplib + email); no dependencies.
"""
from __future__ import annotations
import logging
import os
import smtplib
import socket
import ssl
import threading
from email.message import EmailMessage
from typing import Optional

log = logging.getLogger("krey.notify")

# Serialises sends so the brief IPv4-only DNS override below can't overlap another send.
_send_lock = threading.Lock()


class _force_ipv4:
    """Context manager: resolve hostnames to IPv4 (A records) only, for its duration.

    Railway (and many container hosts) hand the container an IPv6 address but no IPv6
    egress route. Gmail's smtp host has AAAA records, so smtplib tries IPv6 first and
    connect() fails immediately with OSError(101, 'Network is unreachable'). Pinning
    getaddrinfo to AF_INET makes smtplib use the routable IPv4 path. smtplib keeps the
    hostname for STARTTLS SNI + cert verification, so TLS is unaffected. Process-global
    for its short window, so it runs under _send_lock.
    """
    def __enter__(self):
        self._orig = socket.getaddrinfo
        def ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
            return self._orig(host, port, socket.AF_INET, type, proto, flags)
        socket.getaddrinfo = ipv4_only
        return self
    def __exit__(self, *exc):
        socket.getaddrinfo = self._orig
        return False


def _cfg() -> dict:
    return {
        "host": os.environ.get("KREY_SMTP_HOST"),
        "port": int(os.environ.get("KREY_SMTP_PORT") or "587"),
        "user": os.environ.get("KREY_SMTP_USER"),
        "pw": os.environ.get("KREY_SMTP_PASS"),
        "to": os.environ.get("KREY_FEEDBACK_EMAIL_TO"),
        "sender": os.environ.get("KREY_FEEDBACK_EMAIL_FROM") or os.environ.get("KREY_SMTP_USER"),
        # HTTP email API (Resend) over 443 — the reliable path where the host blocks SMTP
        # ports (Railway blocks 25/465/587). Sender defaults to Resend's shared onboarding
        # address, which needs NO domain verification but can only deliver to the Resend
        # account's own email — fine for alpha feedback landing in the team inbox.
        "resend_key": os.environ.get("KREY_RESEND_API_KEY"),
        "resend_from": os.environ.get("KREY_RESEND_FROM") or "Krey Alpha <onboarding@resend.dev>",
    }


def smtp_configured() -> bool:
    """True only when host + user + pass + a recipient are all present."""
    c = _cfg()
    return bool(c["host"] and c["user"] and c["pw"] and c["to"])


def email_configured() -> bool:
    """True when ANY transport can send: Resend (preferred) or SMTP, plus a recipient."""
    c = _cfg()
    return bool(c["to"] and (c["resend_key"] or (c["host"] and c["user"] and c["pw"])))


def _subject_and_body(ticket: dict) -> tuple:
    sev = ticket.get("severity", "normal")
    kind = ticket.get("kind", "?")
    dedup = ticket.get("dedup_key", "")
    # Unique, informative subject per ticket. The old subject was identical every time
    # (dedup is derived from severity/kind, not the note), so Gmail threaded them all into
    # one collapsed conversation and spam filters disliked the repetition. Include the
    # timestamp + a snippet of what the user actually said so each email is distinct.
    created = ticket.get("created_at", "") or ""
    tshort = created[5:16].replace("T", " ") if len(created) >= 16 else created  # MM-DD HH:MM
    note = ticket.get("note") or ""
    snippet = ""
    for line in note.splitlines():
        ls = line.strip()
        if ls.startswith("Other notes:"):
            snippet = ls[len("Other notes:"):].strip(); break
    if not snippet:
        for line in note.splitlines():
            ls = line.strip().lstrip("•").strip()
            if ls and not ls.startswith(("ALPHA TWIN", "From:", "Full read", "Confirmed", "(no")):
                snippet = ls; break
    if len(snippet) > 60:
        snippet = snippet[:59] + "…"
    subject = f"Krey alpha feedback · {tshort} · {sev}" + (f" · {snippet}" if snippet else f" · {dedup}")
    body = "\n".join([
        "New alpha Twin Check feedback.",
        "",
        f"severity : {sev}",
        f"kind     : {kind}",
        f"route    : {ticket.get('route')}",
        f"screen   : {ticket.get('screen')}",
        f"device-specific : {ticket.get('device_specific')}",
        f"dedup    : {dedup}",
        "",
        "--- what the user reported ---",
        ticket.get("note") or "(no note)",
    ])
    return subject, body


def build_message(ticket: dict, cfg: Optional[dict] = None) -> EmailMessage:
    """Compose the plain-text feedback email from a /feedback ticket. No I/O."""
    c = cfg or _cfg()
    subject, body = _subject_and_body(ticket)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = c["sender"] or ""
    msg["To"] = c["to"] or ""
    msg.set_content(body)
    return msg


def _send_via_resend(ticket: dict, c: dict, dedup: str) -> bool:
    """Send through the Resend HTTP API over 443 (works where SMTP ports are blocked).
    Best-effort; logs the outcome and never raises."""
    import json
    import urllib.request
    subject, body = _subject_and_body(ticket)
    recipients = [x.strip() for x in (c["to"] or "").split(",") if x.strip()]
    payload = json.dumps({"from": c["resend_from"], "to": recipients,
                          "subject": subject, "text": body}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, method="POST",
        headers={"Authorization": f"Bearer {c['resend_key']}", "Content-Type": "application/json",
                 # A real User-Agent is required: the default 'Python-urllib' trips Cloudflare's
                 # bot filter in front of api.resend.com (HTTP 403, 'error code: 1010') before the
                 # request reaches Resend. Accept keeps the API returning JSON errors.
                 "User-Agent": "Krey-Alpha-Feedback/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = 200 <= r.status < 300
        log.info("feedback email sent via resend to=%s dedup=%s status=%s", c["to"], dedup, "ok" if ok else "?")
        return ok
    except Exception as e:
        # urllib raises HTTPError with the API's reason (e.g. 403 domain not verified,
        # 401 bad key) — surface it without leaking the key.
        detail = getattr(e, "read", None)
        body_txt = ""
        try:
            body_txt = detail().decode("utf-8")[:300] if detail else ""
        except Exception:
            pass
        log.warning("feedback email FAILED via resend to=%s dedup=%s err=%r %s",
                    c["to"], dedup, e, body_txt)
        return False


def send_feedback_email(ticket: dict) -> bool:
    """
    Send the feedback ticket by email. Best-effort: returns True on a successful send,
    False if unconfigured OR on any error — it never raises into the caller (the endpoint
    stays fast and reliable; the log sink is always the backstop).

    Transport order: Resend HTTP API (443) if a key is set — the reliable path on hosts
    that block SMTP ports (Railway) — otherwise raw SMTP.
    """
    c = _cfg()
    dedup = ticket.get("dedup_key", "?")
    if c["resend_key"] and c["to"]:
        return _send_via_resend(ticket, c, dedup)
    if not smtp_configured():
        return False
    try:
        msg = build_message(ticket, c)
        ctx = ssl.create_default_context()
        with _send_lock, _force_ipv4():
            if c["port"] == 465:
                with smtplib.SMTP_SSL(c["host"], c["port"], timeout=15, context=ctx) as s:
                    s.login(c["user"], c["pw"])
                    s.send_message(msg)
            else:
                with smtplib.SMTP(c["host"], c["port"], timeout=15) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.ehlo()
                    s.login(c["user"], c["pw"])
                    s.send_message(msg)
        # Success is logged (not just the failure) so a working SMTP path is
        # observable in the host logs — the response's `emailed` flag only means
        # "configured", the real send happens here in the background.
        log.info("feedback email sent host=%s port=%s to=%s dedup=%s",
                 c["host"], c["port"], c["to"], dedup)
        return True
    except Exception as e:
        # Best-effort: never raises into the request, but the reason MUST be
        # visible — a silent swallow is why a misconfigured App Password looked
        # like "emailed" while nothing arrived. %r keeps the SMTP class + code
        # (e.g. SMTPAuthenticationError 535) without leaking the password.
        log.warning("feedback email FAILED host=%s port=%s user=%s dedup=%s err=%r",
                    c["host"], c["port"], c["user"], dedup, e)
        return False
