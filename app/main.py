"""
Krey avatar sub-project — Service A, slice 1: skin-tone extraction API.

One endpoint that takes a photo and returns the skin_tone slice of the body_models
record (spec section 4). No GPU, no training. This is the cheapest end-to-end slice —
it proves the whole toolchain (deploy, API, contract shape) before anything expensive.

Run locally:
    pip install -r requirements.txt
    uvicorn app.main:app --reload
    # POST an image:  curl -F "file=@face.jpg" http://127.0.0.1:8000/twin/extract-skin
"""
from __future__ import annotations
from fastapi import FastAPI, UploadFile, File, HTTPException
import numpy as np

from app import monk
from app.skin_tone import extract_skin_samples

app = FastAPI(title="Krey Avatar — Service A (skin tone)", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "twin-extraction", "slice": "skin-tone-v0"}


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
