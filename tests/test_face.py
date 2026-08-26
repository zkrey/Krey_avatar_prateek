"""
Face-orchestrator verification — composing skin + hair/eye slices into body_models and
the §6 recognition score, plus the /twin/extract-face endpoint wiring.

`assemble_face` is pure/deterministic given samples, so the composition is fully tested
without a photo. The endpoint test uses FastAPI's TestClient; in the sandbox the hair/iris
samplers are the documented stub, so a synthetic frame exercises the degrade-cleanly path
(skin only, or no-face) and confirms the analytics spine rides along.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from fastapi.testclient import TestClient

from app import face
from app.analytics import MemorySink
from app.main import app, analytics


# ---- pure composition (no photo, no model) -------------------------------------------

def test_assemble_face_composes_all_four_slices():
    record = face.assemble_face(
        skin_samples=[(180, 140, 120)] * 6,
        hair_samples=[(28, 24, 22)] * 6,                 # black
        iris_samples=[(60, 40, 30)] * 6,                 # dark brown
        hair_features={"coherence": 0.90, "curl_frequency": 0.05},   # straight
    )
    assert record["skin_tone"]["value"] is not None
    assert record["hair_colour"]["value"] == "black"
    assert record["eye_colour"]["value"] == "dark_brown"
    assert record["hair_texture"]["value"] == "straight"
    # All four FACE attributes present. Full §6 coverage also needs landmark_coverage
    # (the measurements slice, weight 0.25), so a face-only record tops out at 0.75.
    rec = record["avatar_confidence"]
    assert rec["weight_coverage"] == 0.75 and rec["surfaced_to_user"] is False


def test_assemble_face_skin_only_degrades_cleanly():
    record = face.assemble_face(skin_samples=[(180, 140, 120)] * 6)
    assert record["skin_tone"]["value"] is not None
    assert record["hair_colour"] is None and record["eye_colour"] is None
    # texture is the honest stub (not measured) -> excluded from coverage.
    assert record["hair_texture"]["available"] is False
    assert face.face_slices_present(record) == ["skin_tone"]
    # only skin present of the face slices; recognition still computes, coverage partial.
    assert record["avatar_confidence"]["weight_coverage"] < 1.0


def test_adding_hair_and_eye_lifts_coverage():
    skin_only = face.assemble_face(skin_samples=[(180, 140, 120)] * 6)
    with_face = face.assemble_face(
        skin_samples=[(180, 140, 120)] * 6,
        hair_samples=[(58, 42, 32)] * 6,
        iris_samples=[(108, 74, 50)] * 6,
    )
    assert (with_face["avatar_confidence"]["weight_coverage"]
            > skin_only["avatar_confidence"]["weight_coverage"])


def test_face_slices_present_ignores_none_and_stub():
    empty = face.assemble_face()               # nothing supplied
    assert face.face_slices_present(empty) == []


# ---- endpoint wiring ------------------------------------------------------------------

def _png_bytes(colour=(120, 120, 120)):
    import cv2
    img = np.full((64, 64, 3), colour, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def test_extract_face_endpoint_returns_structure_and_emits_event():
    client = TestClient(app)
    sink, restore = MemorySink(), analytics.sink
    analytics.sink = sink
    try:
        resp = client.post(
            "/twin/extract-face",
            files={"file": ("frame.png", _png_bytes(), "image/png")},
            data={"session_id": "sess-test", "guest_id": "guest-test", "surface": "onboarding"},
        )
    finally:
        analytics.sink = restore

    assert resp.status_code == 200
    body = resp.json()
    assert "eligibility" in body and "body_models" in body

    # Exactly one analytics event fired, carrying the spine (face found or not).
    assert len(sink.events) == 1
    assert sink.events[0]["session_id"] == "sess-test"
    assert sink.events[0]["guest_id"] == "guest-test"


def test_extract_face_empty_file_is_rejected():
    client = TestClient(app)
    resp = client.post("/twin/extract-face",
                       files={"file": ("empty.png", b"", "image/png")})
    assert resp.status_code == 400


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
