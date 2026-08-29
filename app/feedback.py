"""
Feedback intake core — the live→sandbox→production loop's front door (pure stdlib).

A live report (a crash, a broken feature, "this button is off-screen on my Redmi") is
normalized here into a deterministic *ticket* the rest of the loop can act on:
  live report  ->  ticket  ->  GitHub issue  ->  sandbox debug session  ->  PR
                                                   -> human-expert gate -> CI -> deploy

This module is the tested heart (mirrors monk.py / measure_core.py): no network, no
GitHub, no models. It validates the report, classifies severity, decides whether the
report is *device-specific* (routes to the device farm), and computes a stable dedup key
so the same bug reported by 500 users collapses to one ticket instead of 500.

Guardrail: a feedback report is NOT biometric. It carries device/OS/screen/note text and
IDs of recent analytics events — never a photo, never a body measurement. The endpoint
that wraps this is therefore ungated (no canRender): telling us a button is broken must
never require an account or a verified DOB.
"""
from __future__ import annotations
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

SEVERITIES = ("blocker", "high", "normal", "low")
DEFAULT_SEVERITY = "normal"

# A report whose device/os/screen is filled in enough to reproduce on a device farm.
# "Looks wrong on one phone" is only actionable if we know which phone + which screen.
_VISUAL_WORDS = re.compile(
    r"\b(button|layout|off[- ]?screen|overlap|cut ?off|misplaced|clipped|"
    r"crop|font|too (?:big|small|large)|overflow|misaligned|hidden|"
    r"can'?t (?:see|tap|reach)|not visible|scroll)\b",
    re.IGNORECASE,
)
# Stems (crash-es, freez-ing, hang-s), so no trailing \b — match the word's prefix.
_CRASH_WORDS = re.compile(r"\b(crash|freez|hang|force ?clos|anr|white ?screen|black ?screen)",
                          re.IGNORECASE)

_MAX_NOTE = 4000        # keep tickets small; a novel is a support ticket, not a bug
_MAX_EVENTS = 25        # recent_event_ids we thread through for the sandbox to replay


def _clean(text: Optional[str], limit: int) -> str:
    """Trim to a sane length; collapse nothing — the sandbox wants the words verbatim."""
    if not text:
        return ""
    t = str(text).strip()
    return t[:limit]


def normalize_severity(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    return v if v in SEVERITIES else DEFAULT_SEVERITY


def classify_report(note: str, screen: str) -> dict:
    """Derive routing signals from the free text: is it a crash, is it visual, and does it
    look device-specific (a visual bug we can only see by rendering on that device)."""
    blob = f"{note} {screen}"
    is_crash = bool(_CRASH_WORDS.search(blob))
    is_visual = bool(_VISUAL_WORDS.search(blob))
    return {
        "is_crash": is_crash,
        "is_visual": is_visual,
        "kind": "crash" if is_crash else ("visual" if is_visual else "functional"),
    }


def is_device_specific(device: str, os_name: str, os_version: str, kind: str) -> bool:
    """A report routes to the DEVICE FARM only when it is a visual/layout bug AND we know
    the device to reproduce on. A crash reproduces from a stack trace; a logic bug from a
    unit test; but "the CTA is off-screen on a Redmi Note 12" can only be *seen* by
    rendering the real screen on that real (or emulated) device — that's the device farm's
    whole reason to exist. No device named -> can't target a farm -> not device-specific."""
    if kind != "visual":
        return False
    return bool((device or "").strip()) and bool((os_name or "").strip())


def dedup_key(report: dict, routing: dict) -> str:
    """Stable short hash so identical bugs collapse to one ticket. Keyed on the STABLE
    surface of the bug — screen, app_version, os, kind, and the device only when the bug is
    device-specific — never on the free-text note (every user phrases it differently)."""
    parts = [
        _clean(report.get("screen"), 120).lower(),
        _clean(report.get("app_version"), 40).lower(),
        _clean(report.get("os"), 40).lower(),
        routing["kind"],
    ]
    if routing["route"] == "device_farm":
        parts.append(_clean(report.get("device"), 80).lower())
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def build_ticket(report: dict, now: Optional[datetime] = None) -> dict:
    """
    Turn a raw live report into a normalized ticket. Deterministic given `now`.

    Required: `note` (what's wrong) OR `screen` (where) — one of them, so a ticket always
    says at least where or what. Everything else degrades to a sensible default.

    Returns a ticket dict: the routing decision, the severity, the dedup key, a bounded
    copy of the report fields, and the recent_event_ids the sandbox replays. No I/O.
    """
    note = _clean(report.get("note"), _MAX_NOTE)
    screen = _clean(report.get("screen"), 120)
    if not note and not screen:
        raise ValueError("feedback needs at least a note (what's wrong) or a screen (where)")

    severity = normalize_severity(report.get("severity"))
    routing = classify_report(note, screen)
    device = _clean(report.get("device"), 80)
    os_name = _clean(report.get("os"), 40)
    os_version = _clean(report.get("os_version"), 40)

    device_specific = is_device_specific(device, os_name, os_version, routing["kind"])
    # A crash is auto-escalated: a report that says "crash" is at least high severity.
    if routing["is_crash"] and severity in ("normal", "low"):
        severity = "high"

    routing["route"] = "device_farm" if device_specific else "standard"
    routing["device_specific"] = device_specific

    event_ids = report.get("recent_event_ids") or []
    if not isinstance(event_ids, (list, tuple)):
        event_ids = [event_ids]
    event_ids = [str(e)[:64] for e in event_ids][:_MAX_EVENTS]

    ts = (now or datetime.now(timezone.utc))
    ticket = {
        "ticket_version": "feedback-0.1.0",
        "created_at": ts.astimezone(timezone.utc).isoformat(),
        "severity": severity,
        "kind": routing["kind"],
        "route": routing["route"],                 # standard | device_farm
        "device_specific": device_specific,
        "device": device or None,
        "os": os_name or None,
        "os_version": os_version or None,
        "app_version": _clean(report.get("app_version"), 40) or None,
        "screen": screen or None,
        "note": note or None,
        "screenshot_ref": _clean(report.get("screenshot_ref"), 400) or None,
        "recent_event_ids": event_ids,
        "reported_by": _clean(report.get("reported_by"), 80) or None,   # user_id/guest_id only
        "signals": {"is_crash": routing["is_crash"], "is_visual": routing["is_visual"]},
    }
    ticket["dedup_key"] = dedup_key(report, routing)
    ticket["issue_labels"] = issue_labels(ticket)
    return ticket


def issue_labels(ticket: dict) -> list:
    """The GitHub labels the issue-creation step will apply. `sandbox-debug` is the label
    a Claude Code Remote trigger watches to fire a sandbox session; `device-farm` tells the
    CI reproduction step to book a real device. Guardrail note stays a human decision."""
    labels = ["from-live", f"sev-{ticket['severity']}", ticket["kind"]]
    labels.append("sandbox-debug")
    if ticket["route"] == "device_farm":
        labels.append("device-farm")
    if ticket["severity"] == "blocker":
        labels.append("priority")
    return labels
