"""
Krey avatar sub-project — Service A: twin-extraction API.

Two GPU-free extraction slices that fill the body_models record (spec §4):
  - slice 1  POST /twin/extract-skin          -> skin_tone slice (deterministic Monk)
  - slice 2  POST /twin/extract-measurements  -> measurements + shape + accuracy ledger

Eligibility is NOT enforced here: per the invariants, account + verified-DOB gating
lives at a single `canRender` chokepoint (slice 3), never scattered per feature.
These endpoints assume that gate has already passed upstream.

Run locally:
    pip install -r requirements.txt
    uvicorn app.main:app --reload
    # skin:          curl -F "file=@face.jpg" http://127.0.0.1:8000/twin/extract-skin
    # measurements:  curl -F "file=@body.jpg" -F height=170 -F weight=65 -F sex=2 \\
    #                     http://127.0.0.1:8000/twin/extract-measurements
"""
from __future__ import annotations
import os
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import numpy as np

from app import monk
from app.skin_tone import extract_skin_samples
from app import measurements as body

app = FastAPI(title="Krey Avatar — Service A (twin extraction)", version="0.2.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "twin-extraction", "slices": ["skin-tone-v0", "measure-v0"]}


@app.post("/twin/extract-skin")
async def extract_skin(file: UploadFile = File(...)):
    import cv2  # lazy: keeps module import light

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not decode image")

    found = extract_skin_samples(img)
    if not found["ok"]:
        # No usable face -> hand back to the eligibility cascade (Stage 0/1 retake).
        return {
            "eligibility": {"passed": False, "stage": 0, "quality_flags": ["no_face"]},
            "monk_tone": None,
        }

    monk_tone = monk.classify(found["samples"])
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
):
    import cv2  # lazy: keeps module import light

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
        # No usable body -> hand back to the eligibility cascade's retake path.
        return {
            "eligibility": {"passed": False, "stage": 0, "quality_flags": [result["reason"]]},
            "body_models": None,
        }

    return {
        "eligibility": {"passed": True, "stage": 2, "quality_flags": []},
        "scale_px_per_cm": result["scale_px_per_cm"],
        "body_models": result["body_models"],
    }
