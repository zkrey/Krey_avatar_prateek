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


def iris_landmarks_px(img_bgr, model_path: Optional[str] = None) -> Tuple[list, list]:
    """(left_iris, right_iris) pixel points via FaceLandmarker. ([], []) if model absent."""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    path = model_path or _face_model_path()
    if not os.path.exists(path):
        return [], []
    h, w = img_bgr.shape[:2]
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    options = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=path),
        running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=1,
    )
    with mp_vision.FaceLandmarker.create_from_options(options) as fl:
        result = fl.detect(mp_image)
    if not result.face_landmarks:
        return [], []
    lm = result.face_landmarks[0]
    if len(lm) <= max(RIGHT_IRIS):          # model built without the iris/attention head
        return [], []
    left = [(lm[i].x * w, lm[i].y * h) for i in LEFT_IRIS]
    right = [(lm[i].x * w, lm[i].y * h) for i in RIGHT_IRIS]
    return left, right


def sample_hair_and_eyes(img_bgr):
    """
    Run both models and return (hair_samples, iris_samples, hair_region_bgr) for the face
    endpoint. Each model is independent and failure-isolated: a missing/broken model just
    yields empties for its slice, so the endpoint still composes whatever IS available.
    """
    hair_samples: List[RGB] = []
    hair_region = None
    iris_samples: List[RGB] = []

    try:
        mask = hair_mask(img_bgr)
        if mask is not None:
            hair_samples, hair_region = hair_samples_from_mask(img_bgr, mask)
    except Exception:
        pass

    try:
        left, right = iris_landmarks_px(img_bgr)
        iris_samples = (iris_samples_from_landmarks(img_bgr, left)
                        + iris_samples_from_landmarks(img_bgr, right))
    except Exception:
        pass

    return hair_samples, iris_samples, hair_region
