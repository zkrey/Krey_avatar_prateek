"""
Deterministic verification of the feedback-loop intake — the live->sandbox->production
front door. Pure-core tests (build_ticket routing, severity, dedup, device-farm routing)
plus endpoint-wiring tests (ungated, emits analytics, returns the ticket). No network,
no GitHub, no models.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app import feedback as fb
from app.analytics import MemorySink
from app.main import app, analytics

client = TestClient(app)
FIXED = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


# ---- pure core: validation ------------------------------------------------------------
def test_needs_note_or_screen():
    with pytest.raises(ValueError):
        fb.build_ticket({"device": "Pixel 8"})


def test_note_alone_is_enough():
    t = fb.build_ticket({"note": "checkout fails silently"}, now=FIXED)
    assert t["note"] == "checkout fails silently"
    assert t["created_at"] == "2026-08-29T12:00:00+00:00"


def test_screen_alone_is_enough():
    t = fb.build_ticket({"screen": "Fit Result"}, now=FIXED)
    assert t["screen"] == "Fit Result"


# ---- severity -------------------------------------------------------------------------
def test_unknown_severity_defaults_normal():
    assert fb.build_ticket({"note": "x", "severity": "spicy"})["severity"] == "normal"


def test_crash_escalates_normal_to_high():
    t = fb.build_ticket({"note": "app crashes on open", "severity": "normal"})
    assert t["severity"] == "high"
    assert t["kind"] == "crash"


def test_crash_does_not_downgrade_blocker():
    t = fb.build_ticket({"note": "crash", "severity": "blocker"})
    assert t["severity"] == "blocker"
    assert "priority" in t["issue_labels"]


# ---- routing / device farm ------------------------------------------------------------
def test_visual_bug_with_device_routes_to_device_farm():
    t = fb.build_ticket({
        "note": "the Try On button is off-screen at the bottom",
        "screen": "Fit Result", "device": "Redmi Note 12", "os": "Android", "os_version": "13",
    })
    assert t["kind"] == "visual"
    assert t["route"] == "device_farm"
    assert t["device_specific"] is True
    assert "device-farm" in t["issue_labels"]


def test_visual_bug_without_device_stays_standard():
    # Can't book a farm device we can't name -> standard path, not device_farm.
    t = fb.build_ticket({"note": "button is misplaced and overlaps the header"})
    assert t["kind"] == "visual"
    assert t["route"] == "standard"
    assert t["device_specific"] is False
    assert "device-farm" not in t["issue_labels"]


def test_functional_bug_is_not_device_specific_even_with_device():
    t = fb.build_ticket({"note": "wrong size recommended", "device": "iPhone 14", "os": "iOS"})
    assert t["kind"] == "functional"
    assert t["route"] == "standard"


def test_sandbox_debug_label_always_present():
    t = fb.build_ticket({"note": "anything"})
    assert "sandbox-debug" in t["issue_labels"]
    assert "from-live" in t["issue_labels"]


# ---- dedup ----------------------------------------------------------------------------
def test_same_bug_different_words_same_key():
    a = fb.build_ticket({"note": "the CTA is off-screen", "screen": "Fit Result",
                         "device": "Redmi Note 12", "os": "Android", "app_version": "1.2.0"})
    b = fb.build_ticket({"note": "cannot see the button, it's cut off at the bottom",
                         "screen": "Fit Result", "device": "Redmi Note 12", "os": "Android",
                         "app_version": "1.2.0"})
    assert a["dedup_key"] == b["dedup_key"]


def test_different_screen_different_key():
    a = fb.build_ticket({"note": "button off-screen", "screen": "Fit Result",
                         "device": "Redmi Note 12", "os": "Android"})
    b = fb.build_ticket({"note": "button off-screen", "screen": "Home",
                         "device": "Redmi Note 12", "os": "Android"})
    assert a["dedup_key"] != b["dedup_key"]


def test_device_only_matters_for_device_specific_dedup():
    # A functional bug's key ignores device (bug isn't device-bound); same key across phones.
    a = fb.build_ticket({"note": "wrong size", "screen": "Fit", "device": "iPhone 14", "os": "iOS"})
    b = fb.build_ticket({"note": "wrong size", "screen": "Fit", "device": "Pixel 8", "os": "iOS"})
    assert a["dedup_key"] == b["dedup_key"]


# ---- bounds / hygiene -----------------------------------------------------------------
def test_note_is_bounded():
    t = fb.build_ticket({"note": "x" * 10000})
    assert len(t["note"]) == fb._MAX_NOTE


def test_recent_event_ids_bounded_and_stringified():
    t = fb.build_ticket({"note": "x", "recent_event_ids": list(range(100))})
    assert len(t["recent_event_ids"]) == fb._MAX_EVENTS
    assert all(isinstance(e, str) for e in t["recent_event_ids"])


def test_no_biometric_fields_leak_into_ticket():
    # Even if a client stuffs extra keys, the ticket only carries the known-safe surface.
    t = fb.build_ticket({"note": "x", "photo": "b64...", "measurements": {"waist": 80}})
    assert "photo" not in t and "measurements" not in t


# ---- endpoint wiring ------------------------------------------------------------------
def test_endpoint_returns_ticket_and_is_ungated():
    sink = MemorySink()
    analytics.sink = sink
    r = client.post("/feedback", json={
        "note": "Try On button off-screen", "screen": "Fit Result",
        "device": "Redmi Note 12", "os": "Android", "os_version": "13", "app_version": "1.2.0",
        "user_id": "u-1",
    })
    assert r.status_code == 200            # no eligibility gate — no account/DOB required
    body = r.json()
    assert body["status"] == "queued"
    assert body["ticket"]["route"] == "device_farm"
    events = [e for e in sink.events if e["event"] == "feedback"]
    assert len(events) == 1
    assert events[0]["props"]["route"] == "device_farm"
    assert events[0]["props"]["severity"] in fb.SEVERITIES


def test_endpoint_guest_needs_no_account():
    sink = MemorySink()
    analytics.sink = sink
    r = client.post("/feedback", json={"note": "checkout hangs"})
    assert r.status_code == 200
    assert r.json()["ticket"]["kind"] == "crash"     # 'hangs' -> crash class


def test_endpoint_rejects_empty_report():
    r = client.post("/feedback", json={"device": "Pixel 8"})
    assert r.status_code == 400
