"""
Krey avatar sub-project — Service A: twin-extraction API.

Two GPU-free extraction slices that fill the body_models record (spec §4):
  - slice 1  POST /twin/extract-skin          -> skin_tone slice (deterministic Monk)
  - slice 2  POST /twin/extract-measurements  -> measurements + shape + accuracy ledger

Every call emits a structured analytics event carrying the common spine (see
app/analytics.py) — "the gates are the events". Eligibility is NOT enforced here: per
the invariants, account + verified-DOB gating lives at the single `canRender` chokepoint
(slice 3), never scattered per feature.

Run locally:
    pip install -r requirements.txt
    uvicorn app.main:app --reload
    # skin:          curl -F "file=@face.jpg" http://127.0.0.1:8000/twin/extract-skin
    # measurements:  curl -F "file=@body.jpg" -F height=170 -F weight=65 -F sex=2 \\
    #                     http://127.0.0.1:8000/twin/extract-measurements
"""
from __future__ import annotations
import os
import uuid
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import numpy as np

from app import monk
from app.skin_tone import extract_skin_samples
from app import measurements as body
from app.analytics import Analytics, Spine
from app.recognition import recognition_from_body_models

app = FastAPI(title="Krey Avatar — Service A (twin extraction)", version="0.3.0")

# Default sink logs JSON lines; swap for the warehouse / Events service in production.
analytics = Analytics()


def _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, entry_point) -> Spine:
    """Build the analytics spine from client-provided context, with safe demo defaults."""
    if not user_id and not guest_id:
        guest_id = f"guest-{uuid.uuid4().hex[:12]}"
    return Spine(
        session_id=session_id or f"sess-{uuid.uuid4().hex[:12]}",
        surface=surface or "onboarding",
        app_version=app_version or "0.0.0",
        device_os=device_os or "unknown",
        signed_in=bool(user_id),
        user_id=user_id,
        guest_id=guest_id,
        entry_point=entry_point,
        region=region,
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "twin-extraction", "slices": ["skin-tone-v0", "measure-v0"]}


@app.post("/twin/extract-skin")
async def extract_skin(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    guest_id: Optional[str] = Form(None),
    surface: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    device_os: Optional[str] = Form(None),
):
    import cv2  # lazy: keeps module import light

    spine = _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, None)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not decode image")

    found = extract_skin_samples(img)
    if not found["ok"]:
        # No usable face -> Stage-0 retake signal; emit it.
        analytics.input_cascade(spine, passed=False, stage=0, quality_flags=["no_face"])
        return {
            "eligibility": {"passed": False, "stage": 0, "quality_flags": ["no_face"]},
            "monk_tone": None,
        }

    monk_tone = monk.classify(found["samples"])
    analytics.twin_extracted(spine, slice="skin", model=monk_tone["model"],
                             confidence=monk_tone["confidence"], needs_confirm=monk_tone["needs_confirm"])
    return {
        "eligibility": {"passed": True, "stage": 2, "quality_flags": []},
        "monk_tone": monk_tone,
        "detector": found["detector"],
    }


@app.post("/twin/extract-measurements")
async def extract_measurements(
    file: UploadFile = File(...),          # front-body photo
    height: float = Form(...),             # declared height (cm) — the scale anchor
    weight: float = Form(...),             # declared weight (kg) — for BMI
    sex: int = Form(...),                  # 1 = male, 2 = female
    body_type: Optional[str] = Form(None), # declared body_type — CROSS-CHECK only
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    guest_id: Optional[str] = Form(None),
    surface: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    device_os: Optional[str] = Form(None),
):
    import cv2  # lazy: keeps module import light

    spine = _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, None)

    # The pose model is large and licensed separately; it is not bundled in the repo.
    if not os.path.exists(body._model_path()):
        raise HTTPException(503, f"pose model not found at {body._model_path()} "
                                 "(set MODELS_DIR to the folder holding pose_landmarker_heavy.task)")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not decode image")

    result = body.compute_measurements(
        img, declared_height_cm=height, declared_weight_kg=weight,
        sex=sex, declared_body_type=body_type,
    )
    if result["status"] != "ok":
        analytics.input_cascade(spine, passed=False, stage=0, quality_flags=[result["reason"]])
        return {
            "eligibility": {"passed": False, "stage": 0, "quality_flags": [result["reason"]]},
            "body_models": None,
        }

    # Attach the §6 recognition score (partial coverage until hair/eye slices exist).
    record = result["body_models"]
    record["avatar_confidence"] = recognition_from_body_models(record)
    analytics.twin_extracted(spine, slice="measurements", model="rule-measure-v0",
                             confidence=record["accuracy_ledger"]["body_confidence"])
    return {
        "eligibility": {"passed": True, "stage": 2, "quality_flags": []},
        "scale_px_per_cm": result["scale_px_per_cm"],
        "body_models": record,
    }
