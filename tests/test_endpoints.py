"""
End-to-end check that the API emits analytics events (spine + funnel), using a
FastAPI TestClient and an in-memory analytics sink. No real server, no network.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import cv2
from fastapi.testclient import TestClient

from app import main
from app.analytics import MemorySink


def _small_jpeg() -> bytes:
    img = np.full((120, 120, 3), 127, np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def test_health():
    client = TestClient(main.app)
    assert client.get("/health").json()["status"] == "ok"


def test_extract_skin_emits_event_and_carries_spine():
    sink = MemorySink()
    main.analytics.sink = sink                         # capture events in memory
    client = TestClient(main.app)

    resp = client.post("/twin/extract-skin",
                       files={"file": ("f.jpg", _small_jpeg(), "image/jpeg")},
                       data={"surface": "onboarding", "region": "IN"})
    assert resp.status_code == 200
    body = resp.json()
    # In this environment face detection can't run, so it's the no-face path...
    assert body["eligibility"]["passed"] is False and body["monk_tone"] is None
    # ...and it emitted a Stage-0 cascade event carrying the spine.
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev["event"] == "input_cascade" and ev["props"]["stage"] == 0
    assert ev["props"]["quality_flags"] == ["no_face"]
    assert ev["surface"] == "onboarding" and ev["region"] == "IN"
    assert ev["guest_id"] and ev["signed_in"] is False    # auto guest, pre-account


def test_empty_upload_is_rejected():
    client = TestClient(main.app)
    resp = client.post("/twin/extract-skin",
                       files={"file": ("f.jpg", b"", "image/jpeg")})
    assert resp.status_code == 400


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
