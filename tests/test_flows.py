"""
API-surface tests for the consolidated Service A flows — capture-session, body-measure,
style-profile, fit-recommend. TestClient only; the heavy model pipelines are monkeypatched
so these test the ENDPOINT wiring: the single eligibility gate, derive-and-discard, the
analytics spine, and response shape — no models, no network.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import pytest
from fastapi.testclient import TestClient

from app.analytics import MemorySink
from app.main import app, analytics, _save_uploads, _discard

client = TestClient(app)
ADULT = "1990-05-01"
MINOR = "2015-05-01"


def _png():
    import numpy as np, cv2
    ok, buf = cv2.imencode(".png", np.full((32, 32, 3), 120, np.uint8))
    return buf.tobytes()


def _files(n=2):
    return [("files", (f"f{i}.png", io.BytesIO(_png()), "image/png")) for i in range(n)]


# ---- health ---------------------------------------------------------------------------
def test_health_lists_the_flows():
    body = client.get("/health").json()
    assert "capture-session" in body["flows"] and "fit-recommend" in body["flows"]


# ---- the single eligibility gate ------------------------------------------------------
def test_capture_blocked_without_account():
    r = client.post("/capture/session", files=_files(),
                    data={"account_present": "false", "dob_verified": "true", "birthdate": ADULT})
    assert r.status_code == 403 and r.json()["detail"]["reason"] == "no_account"


def test_capture_blocks_minor_even_with_everything_else():
    r = client.post("/capture/session", files=_files(),
                    data={"account_present": "true", "dob_verified": "true", "birthdate": MINOR})
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["reason"] == "minor_blocked_by_policy" and d["is_minor"] is True


# ---- capture-session wiring (pipeline monkeypatched) ----------------------------------
def test_capture_runs_when_eligible(monkeypatch):
    import app.capture_session as cs
    monkeypatch.setattr(cs, "analyze_capture", lambda paths: {
        "decision": "accept", "identity": {"overall": 0.84},
        "timeline": {"oldest": "2016-01-01", "newest": "2026-01-01", "n_dated": 5},
        "appearance": {"eye_colour": {"value": "dark_brown"}},
        "n_faces_total": 12, "n_user_faces": 12, "frames": []})
    sink, restore = MemorySink(), analytics.sink
    analytics.sink = sink
    try:
        r = client.post("/capture/session", files=_files(3),
                        data={"account_present": "true", "dob_verified": "true",
                              "birthdate": ADULT, "user_id": "u1"})
    finally:
        analytics.sink = restore
    assert r.status_code == 200
    b = r.json()
    assert b["eligibility"]["passed"] is True and b["decision"] == "accept"
    assert b["identity"]["overall"] == 0.84
    events = {e["event"] for e in sink.events}
    assert "eligibility" in events and "twin_extracted" in events   # the gates are the events


def test_capture_discards_raw_photos(monkeypatch):
    seen = {}
    import app.capture_session as cs
    def fake(paths):
        seen["paths"] = list(paths)
        assert all(os.path.exists(p) for p in paths)      # present DURING processing
        return {"decision": "retake_no_face", "identity": None, "timeline": {},
                "appearance": {}, "n_faces_total": 0, "n_user_faces": 0, "frames": []}
    monkeypatch.setattr(cs, "analyze_capture", fake)
    r = client.post("/capture/session", files=_files(2),
                    data={"account_present": "true", "dob_verified": "true", "birthdate": ADULT})
    assert r.status_code == 200
    assert seen["paths"] and not any(os.path.exists(p) for p in seen["paths"])  # gone after


# ---- persistence (capture -> store -> fetch -> erase) ---------------------------------
def test_capture_persists_for_account_and_can_be_fetched_and_erased(monkeypatch):
    import app.capture_session as cs
    monkeypatch.setattr(cs, "analyze_capture", lambda paths: {
        "decision": "accept", "identity": {"overall": 0.84}, "timeline": {},
        "appearance": {"eye_colour": {"value": "dark_brown", "confidence": 0.99},
                       "skin_tone": {"value": 6, "confidence": 0.6}},
        "n_faces_total": 12, "n_user_faces": 12, "frames": []})
    r = client.post("/capture/session", files=_files(3),
                    data={"account_present": "true", "dob_verified": "true",
                          "birthdate": ADULT, "user_id": "persist-user"})
    assert r.status_code == 200 and r.json()["saved"] is True

    got = client.get("/twins/persist-user")
    assert got.status_code == 200
    rec = got.json()["record"]
    assert rec["eye_colour"]["value"] == "dark_brown" and "avatar_confidence" in rec

    assert client.delete("/twins/persist-user").json()["erased"] is True
    assert client.get("/twins/persist-user").status_code == 404      # erased


def test_guest_capture_does_not_persist(monkeypatch):
    import app.capture_session as cs
    monkeypatch.setattr(cs, "analyze_capture", lambda paths: {
        "decision": "accept", "identity": {"overall": 0.8}, "timeline": {},
        "appearance": {"eye_colour": {"value": "dark_brown", "confidence": 0.9}},
        "n_faces_total": 5, "n_user_faces": 5, "frames": []})
    # no user_id -> a guest -> nothing is stored (biometric persistence needs an account).
    r = client.post("/capture/session", files=_files(2),
                    data={"account_present": "true", "dob_verified": "true", "birthdate": ADULT})
    assert r.status_code == 200 and r.json()["saved"] is False


# ---- body-measure ---------------------------------------------------------------------
def test_body_measure_503_without_pose_model(monkeypatch):
    monkeypatch.setenv("MODELS_DIR", "/nonexistent-models")
    r = client.post("/body/measure", files=_files(),
                    data={"height": "175", "weight": "72", "sex": "1",
                          "account_present": "true", "dob_verified": "true", "birthdate": ADULT})
    assert r.status_code == 503 and "pose model" in r.json()["detail"]


def test_body_measure_gate_blocks_first(monkeypatch):
    # gate is checked BEFORE the model — no account -> 403 even with a missing model.
    monkeypatch.setenv("MODELS_DIR", "/nonexistent-models")
    r = client.post("/body/measure", files=_files(),
                    data={"height": "175", "weight": "72", "sex": "1", "account_present": "false"})
    assert r.status_code == 403


# ---- style-profile (taps) -------------------------------------------------------------
def test_style_profile_from_taps():
    r = client.post("/style/profile", json={"fit_feel": "roomy",
                                            "region_preferences": {"waist": "skim"},
                                            "comfort_offset": {"top": 1}})
    p = r.json()["style_profile"]
    assert p["fit_feel"] == "relaxed" and p["region_preferences"] == {"waist": "relaxed"}
    assert p["comfort_offset"] == {"top": 1}


# ---- fit-recommend --------------------------------------------------------------------
def test_fit_recommend_flatters_and_hides_insecurity():
    body = {"chest": 90.0, "waist": 90.0, "hip": 96.0, "shoulder": 110.0}
    garment = {"cut": "regular", "fabric_stretch": "none", "size_chart": {
        "M": {"chest": 98, "waist": 94, "hip": 104, "shoulder": 116},
        "L": {"chest": 104, "waist": 100, "hip": 110, "shoulder": 122},
        "XL": {"chest": 110, "waist": 106, "hip": 116, "shoulder": 128}}}
    r = client.post("/fit/recommend", json={"body_cm": body, "garment": garment,
                                            "style_profile": {"fit_feel": "true",
                                                              "sensitivities": ["midsection"]}})
    out = r.json()
    assert out["best_size"] in ("L", "XL") and out["why"]
    assert all(bad not in out["why"].lower() for bad in ("fat", "belly", "insecure", "midsection"))


def test_fit_recommend_needs_body_and_garment():
    assert client.post("/fit/recommend", json={"garment": {"size_chart": {}}}).status_code == 400


# ---- helpers --------------------------------------------------------------------------
def test_save_and_discard_roundtrip():
    paths, d = _save_uploads([b"x", b"y"])
    assert len(paths) == 2 and all(os.path.exists(p) for p in paths)
    _discard(paths, d)
    assert not any(os.path.exists(p) for p in paths) and not os.path.exists(d)


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))


# ---- team QA tester page --------------------------------------------------------------
def test_tester_page_served():
    r = client.get("/tester")
    assert r.status_code == 200
    assert "Krey" in r.text and "/twin/extract-skin" in r.text   # twin tab calls the real API
