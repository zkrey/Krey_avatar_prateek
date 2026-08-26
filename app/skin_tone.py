"""
Skin-patch sampling for slice 1.

Locates clean skin regions (forehead + both cheeks), drops over/under-exposed
pixels (Capture Pipeline Spec 4.2), and returns one median RGB per patch to feed
monk.classify(). Heavy deps are imported lazily so this module (and the FastAPI
app) load fine even before mediapipe/opencv are installed — you validate those on
your machine in Claude Code with a real photo.

Face detection: MediaPipe FaceMesh preferred (the on-device pose/landmark engine
in the reference architecture). If mediapipe isn't available, falls back to the
Haar cascade that ships with OpenCV, so slice 1 still runs.
"""
from __future__ import annotations
from typing import List, Tuple
import numpy as np

RGB = Tuple[int, int, int]

# FaceMesh landmark indices for clean skin patches (avoid brows, eyes, lips, hairline).
_FOREHEAD = [10, 151, 9, 8]
_LEFT_CHEEK = [50, 205, 234, 117]
_RIGHT_CHEEK = [280, 425, 454, 346]

_PATCH = 8            # half-size of the square sampled around each landmark (px)
_LOW, _HIGH = 40, 240  # exposure bounds (spec 4.2): drop crushed/blown pixels


def _clean_median(patch_bgr: np.ndarray) -> RGB | None:
    """Median RGB of a patch after dropping over/under-exposed pixels."""
    px = patch_bgr.reshape(-1, 3).astype(np.int16)
    keep = np.all((px > _LOW) & (px < _HIGH), axis=1)
    px = px[keep]
    if len(px) < 4:
        return None
    b, g, r = np.median(px, axis=0)
    return (int(r), int(g), int(b))


def _sample_at(img_bgr, x: int, y: int) -> RGB | None:
    h, w = img_bgr.shape[:2]
    x0, x1 = max(0, x - _PATCH), min(w, x + _PATCH)
    y0, y1 = max(0, y - _PATCH), min(h, y + _PATCH)
    if x1 <= x0 or y1 <= y0:
        return None
    return _clean_median(img_bgr[y0:y1, x0:x1])


def _samples_mediapipe(img_bgr) -> List[RGB]:
    # Modern MediaPipe Tasks FaceLandmarker (the legacy mp.solutions.face_mesh path is
    # gone in current builds). Shares the one landmarker used for iris/gate so skin and
    # eyes come off the same face detection.
    from app.face_pipeline import run_face_landmarker, skin_samples_from_landmarks
    faces = run_face_landmarker(img_bgr, num_faces=1)
    if not faces:
        return []
    return skin_samples_from_landmarks(img_bgr, faces[0])


def _samples_haar(img_bgr) -> List[RGB]:
    import cv2  # lazy
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, 1.1, 5)
    if len(faces) == 0:
        return []
    x, y, w, h = sorted(faces, key=lambda f: f[2] * f[3])[-1]  # largest face
    pts = {
        "forehead": (x + w // 2, y + int(h * 0.18)),
        "left_cheek": (x + int(w * 0.28), y + int(h * 0.62)),
        "right_cheek": (x + int(w * 0.72), y + int(h * 0.62)),
    }
    out: List[RGB] = []
    for px, py in pts.values():
        s = _sample_at(img_bgr, px, py)
        if s:
            out.append(s)
    return out


def extract_skin_samples(img_bgr) -> dict:
    """
    img_bgr: an OpenCV BGR image (numpy array).
    Returns {'samples': [RGB,...], 'detector': str, 'ok': bool, 'detector_error': str|None}.
    Empty samples => no usable face (feeds the eligibility cascade's retake path).

    detector_error surfaces WHY the preferred MediaPipe path fell back — without it a
    broken/unpinned mediapipe build degrades silently to the weak Haar fallback (that
    exact failure happened once, invisibly). See requirements.txt for the pin.
    """
    detector = "mediapipe"
    detector_error = None
    try:
        samples = _samples_mediapipe(img_bgr)
    except Exception as e:
        samples = []
        detector_error = f"mediapipe: {type(e).__name__}: {e}"
    if not samples:
        detector = "haar-fallback"
        try:
            samples = _samples_haar(img_bgr)
        except Exception as e:
            samples = []
            detector_error = (detector_error or "") + f" | haar: {type(e).__name__}: {e}"
    return {"samples": samples, "detector": detector, "ok": len(samples) >= 2,
            "detector_error": detector_error}
