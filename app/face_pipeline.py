"""
Face image pipeline — the model-backed samplers that FEED the deterministic face core.

Two MediaPipe Tasks models turn a face photo into the clean pixel samples that
`app/face.assemble_face` composes:
  - hair_segmenter.tflite  -> hair-probability mask -> clean hair-pixel RGBs (colour)
                              + a hair-region crop (texture features)
  - face_landmarker.task   -> 478 landmarks incl. iris (468-477) -> clean iris-ring RGBs

Same architecture as the pose pipeline (`measurements.py`): heavy deps (cv2, mediapipe)
are lazy-imported inside the model shells, and every NUMERIC step — mask -> samples,
iris landmarks -> samples — is a pure numpy function tested with synthetic arrays, so
the wiring is verified without downloading a model or a GPU. Models live under
MODELS_DIR (same convention as pose); when absent the samplers degrade to empties and
the face endpoint composes whatever IS available (skin).

Models: Apache-2.0, Google MediaPipe. Not bundled — large and fetched separately.
"""
from __future__ import annotations
from typing import List, Optional, Sequence, Tuple
import os
import numpy as np

RGB = Tuple[int, int, int]

# MediaPipe FaceLandmarker iris landmark indices (478-pt model): [centre, ring x4].
LEFT_IRIS = [468, 469, 470, 471, 472]
RIGHT_IRIS = [473, 474, 475, 476, 477]

# Skin uses (40,240); HAIR must keep its dark pixels — black / dark-brown hair (the
# common Indian case) sits at ~20-30, so only crushed shadow and glare are dropped.
_HAIR_LOW, _HAIR_HIGH = 12, 245
_LOW, _HIGH = 40, 240      # iris exposure bounds: drop crushed/blown pixels
_PUPIL_DARK = 25           # below this (all channels) = pupil/lash, not iris colour


def _hair_model_path() -> str:
    return os.path.join(os.environ.get("MODELS_DIR", "models"), "hair_segmenter.tflite")


def _face_model_path() -> str:
    return os.path.join(os.environ.get("MODELS_DIR", "models"), "face_landmarker.task")


# ---------------------------------------------------------------------------
# Pure sampling cores (numpy only — tested with synthetic arrays, no model)
# ---------------------------------------------------------------------------
def hair_samples_from_mask(img_bgr, mask, threshold: float = 0.5,
                           max_samples: int = 400) -> Tuple[List[RGB], Optional[np.ndarray]]:
    """
    Clean hair-pixel RGBs from a hair-probability mask, plus a hair-region crop for the
    texture features. Drops over/under-exposed pixels (spec 4.2); evenly subsamples so a
    big head of hair doesn't dominate. Returns ([] , None) when the mask holds no hair.
    """
    mask = np.asarray(mask, dtype=np.float32)
    while mask.ndim > 2:
        mask = mask[..., 0]
    ys, xs = np.where(mask > threshold)
    if ys.size == 0:
        return [], None

    px = img_bgr[ys, xs].astype(np.int16)                       # BGR rows of hair pixels
    keep = np.all((px > _HAIR_LOW) & (px < _HAIR_HIGH), axis=1)
    px = px[keep]
    if px.shape[0] == 0:
        return [], _crop_bbox(img_bgr, ys, xs)

    if px.shape[0] > max_samples:                               # even subsample
        idx = np.linspace(0, px.shape[0] - 1, max_samples).astype(int)
        px = px[idx]
    samples = [(int(r), int(g), int(b)) for b, g, r in px]      # BGR -> RGB
    return samples, _crop_bbox(img_bgr, ys, xs)


def _crop_bbox(img_bgr, ys, xs) -> Optional[np.ndarray]:
    """Tight bounding-box crop around the mask — the region handed to texture features."""
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    if y1 - y0 < 4 or x1 - x0 < 4:
        return None
    return img_bgr[y0:y1, x0:x1]


def iris_samples_from_landmarks(img_bgr, iris_pts_px: Sequence[Tuple[float, float]]) -> List[RGB]:
    """
    Sample the iris RING from its 5 landmarks ([centre, 4 ring points]). We take an
    annulus between the pupil and the limbus (0.35..0.85 of the iris radius) so the
    dark pupil centre and the sclera edge don't bias the colour. Drops over/under-exposed
    and pupil-dark pixels. Empty list if the geometry is degenerate.
    """
    if len(iris_pts_px) < 5:
        return []
    cx, cy = iris_pts_px[0]
    ring = iris_pts_px[1:5]
    radius = float(np.mean([np.hypot(px - cx, py - cy) for px, py in ring]))
    if radius < 1.5:
        return []

    h, w = img_bgr.shape[:2]
    r_lo, r_hi = 0.35 * radius, 0.85 * radius
    y0, y1 = max(0, int(cy - radius)), min(h, int(cy + radius) + 1)
    x0, x1 = max(0, int(cx - radius)), min(w, int(cx + radius) + 1)
    if y1 <= y0 or x1 <= x0:
        return []

    out: List[RGB] = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            d = np.hypot(x - cx, y - cy)
            if not (r_lo <= d <= r_hi):
                continue
            b, g, r = (int(v) for v in img_bgr[y, x])
            if min(b, g, r) < _PUPIL_DARK or max(b, g, r) > _HIGH:
                continue
            out.append((r, g, b))
    return out


# ---------------------------------------------------------------------------
# Model shells (lazy MediaPipe; degrade to empties when a model is absent)
# ---------------------------------------------------------------------------
def hair_mask(img_bgr, model_path: Optional[str] = None):
    """Hair-probability mask via MediaPipe hair_segmenter. None if the model is absent."""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    path = model_path or _hair_model_path()
    if not os.path.exists(path):
        return None
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    options = mp_vision.ImageSegmenterOptions(
        base_options=mp_python.BaseOptions(model_asset_path=path),
        running_mode=mp_vision.RunningMode.IMAGE,
        output_confidence_masks=True,
    )
    with mp_vision.ImageSegmenter.create_from_options(options) as seg:
        result = seg.segment(mp_image)
    masks = result.confidence_masks
    if not masks:
        return None
    # hair_segmenter categories: 0 = background, 1 = hair.
    hair = masks[1] if len(masks) > 1 else masks[0]
    return hair.numpy_view().astype(np.float32)


def run_face_landmarker(img_bgr, num_faces: int = 3, min_conf: float = 0.5,
                        model_path: Optional[str] = None, max_side: int = 1600) -> list:
    """
    Detect faces and return one list of (x_px, y_px) landmark points PER face, in the
    ORIGINAL image's pixel coordinates. Detects up to `num_faces` so the caller can gate
    on 'exactly one face'. Big frames are downscaled for detection only (MediaPipe's face
    detector is tuned for selfie-scale faces); normalized landmarks map back to full res.
    Returns [] when the model is absent or no face is found.
    """
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    path = model_path or _face_model_path()
    if not os.path.exists(path):
        return []
    h, w = img_bgr.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    det = cv2.resize(img_bgr, (int(w * scale), int(h * scale))) if scale < 1.0 else img_bgr
    rgb = cv2.cvtColor(det, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    options = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=path),
        running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=num_faces,
        min_face_detection_confidence=min_conf,
    )
    with mp_vision.FaceLandmarker.create_from_options(options) as fl:
        result = fl.detect(mp_image)
    # normalized landmarks -> ORIGINAL pixel coords (w, h), independent of the det scale.
    return [[(lm.x * w, lm.y * h) for lm in face] for face in result.face_landmarks]


def gate_from_face_count(n_faces: int) -> str:
    """Single-clear-face gate: 0 -> no_face, 1 -> ok, >1 -> multiple_faces. Pure."""
    if n_faces <= 0:
        return "no_face"
    if n_faces > 1:
        return "multiple_faces"
    return "ok"


def iris_points(landmarks_px: Sequence[Tuple[float, float]]) -> Tuple[list, list]:
    """(left_iris, right_iris) 5-point sets from a full landmark list. Pure. ([],[]) if no iris."""
    if len(landmarks_px) <= max(RIGHT_IRIS):    # model built without the iris/attention head
        return [], []
    return ([landmarks_px[i] for i in LEFT_IRIS], [landmarks_px[i] for i in RIGHT_IRIS])


def skin_samples_from_landmarks(img_bgr, landmarks_px: Sequence[Tuple[float, float]]) -> List[RGB]:
    """Clean forehead + cheek skin RGBs from a full landmark list. Pure (reuses skin_tone)."""
    from app.skin_tone import _FOREHEAD, _LEFT_CHEEK, _RIGHT_CHEEK, _sample_at
    out: List[RGB] = []
    for group in (_FOREHEAD, _LEFT_CHEEK, _RIGHT_CHEEK):
        for i in group:
            if i < len(landmarks_px):
                x, y = landmarks_px[i]
                s = _sample_at(img_bgr, int(x), int(y))
                if s:
                    out.append(s)
    return out


def sample_face(img_bgr) -> dict:
    """
    One face-landmark pass (gate + skin + iris) plus the hair segmenter, returning
    everything the face endpoint needs:
        {gate, n_faces, skin_samples, hair_samples, iris_samples, hair_region}
    The gate is the decision: only a single clear face yields extracted samples. On
    no_face / multiple_faces we DON'T trust hair either (a group photo's hair is a
    blend of several heads), so samples come back empty and the endpoint asks for a
    retake. Every model call is failure-isolated so a broken model can't crash the route.
    """
    result = {"gate": "no_face", "n_faces": 0, "skin_samples": [],
              "hair_samples": [], "iris_samples": [], "hair_region": None}
    try:
        faces = run_face_landmarker(img_bgr)
    except Exception:
        faces = []
    result["n_faces"] = len(faces)
    result["gate"] = gate_from_face_count(len(faces))
    if result["gate"] != "ok":
        return result                       # bad input -> retake; trust nothing

    lm = faces[0]
    result["skin_samples"] = skin_samples_from_landmarks(img_bgr, lm)
    left, right = iris_points(lm)
    result["iris_samples"] = (iris_samples_from_landmarks(img_bgr, left)
                              + iris_samples_from_landmarks(img_bgr, right))
    try:
        mask = hair_mask(img_bgr)
        if mask is not None:
            result["hair_samples"], result["hair_region"] = hair_samples_from_mask(img_bgr, mask)
    except Exception:
        pass
    return result
