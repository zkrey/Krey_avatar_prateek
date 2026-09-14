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
import ssl
from email.message import EmailMessage
from typing import Optional

log = logging.getLogger("krey.notify")


def _cfg() -> dict:
    return {
        "host": os.environ.get("KREY_SMTP_HOST"),
        "port": int(os.environ.get("KREY_SMTP_PORT") or "587"),
        "user": os.environ.get("KREY_SMTP_USER"),
        "pw": os.environ.get("KREY_SMTP_PASS"),
        "to": os.environ.get("KREY_FEEDBACK_EMAIL_TO"),
        "sender": os.environ.get("KREY_FEEDBACK_EMAIL_FROM") or os.environ.get("KREY_SMTP_USER"),
    }


def smtp_configured() -> bool:
    """True only when host + user + pass + a recipient are all present."""
    c = _cfg()
    return bool(c["host"] and c["user"] and c["pw"] and c["to"])


def build_message(ticket: dict, cfg: Optional[dict] = None) -> EmailMessage:
    """Compose the plain-text feedback email from a /feedback ticket. No I/O."""
    c = cfg or _cfg()
    sev = ticket.get("severity", "normal")
    kind = ticket.get("kind", "?")
    dedup = ticket.get("dedup_key", "")
    msg = EmailMessage()
    msg["Subject"] = f"Feedback from alpha test · {sev} · {kind} · {dedup}"
    msg["From"] = c["sender"] or ""
    msg["To"] = c["to"] or ""
    body = [
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
    ]
    msg.set_content("\n".join(body))
    return msg


def send_feedback_email(ticket: dict) -> bool:
    """
    Send the feedback ticket by email. Best-effort: returns True on a successful send,
    False if unconfigured OR on any error — it never raises into the caller (the endpoint
    stays fast and reliable; the log sink is always the backstop).
    """
    if not smtp_configured():
        return False
    c = _cfg()
    dedup = ticket.get("dedup_key", "?")
    try:
        msg = build_message(ticket, c)
        ctx = ssl.create_default_context()
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
