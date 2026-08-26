"""
Body-measurement image pipeline — Service A, slice 2.

Front-body photo + DECLARED height/weight/sex (+ optional declared body_type) ->
per-part measurements with confidence, a computed body shape, and the backend
accuracy ledger. GPU-free: MediaPipe's pose landmarker runs on CPU. Heavy deps
(cv2, mediapipe, numpy) are imported lazily so this module and the FastAPI app
load without them — the deterministic contract is tested in `measure_core` without
a photo or the model.

Salvaged from `zkrey/UserImageProcessingAPI` (BodyProcessing.py): pose landmarking,
mask-based pixel height, landmark-derived sample rows, and mask row-width with
torso/limb region isolation. Everything numeric (scale, circumference, confidence,
shape, cross-check, ledger) is delegated to `measure_core`.

Model: pose_landmarker_heavy.task, located via the MODELS_DIR env var (same
convention as her API). Not bundled in the repo — it is large and licensed
separately (Apache-2.0, Google MediaPipe).
"""
from __future__ import annotations
from typing import Optional
from dataclasses import dataclass
import os

from app import measure_core as core
from app.body_models import assemble_body_models

# MediaPipe pose (33-pt) index -> our COCO-17 landmark names.
_MP_TO_COCO = {
    0: "nose", 2: "left_eye", 5: "right_eye", 7: "left_ear", 8: "right_ear",
    11: "left_shoulder", 12: "right_shoulder", 13: "left_elbow", 14: "right_elbow",
    15: "left_wrist", 16: "right_wrist", 23: "left_hip", 24: "right_hip",
    25: "left_knee", 26: "right_knee", 27: "left_ankle", 28: "right_ankle",
}
# Extra points we still read off MediaPipe for the pixel-height estimate.
_MP_EXTRA = {29: "left_heel", 30: "right_heel", 31: "left_foot_index", 32: "right_foot_index"}

# Landmarks whose visibility gates each measurement's confidence.
_PART_LANDMARKS = {
    "shoulder": ("left_shoulder", "right_shoulder"),
    "chest": ("left_shoulder", "right_shoulder", "left_hip", "right_hip"),
    "waist": ("left_shoulder", "right_shoulder", "left_hip", "right_hip"),
    "hip": ("left_hip", "right_hip"),
    "thigh": ("left_hip", "right_hip", "left_knee", "right_knee"),
    "calf": ("left_knee", "right_knee", "left_ankle", "right_ankle"),
    "bicep": ("left_shoulder", "right_shoulder", "left_elbow", "right_elbow"),
    "forearm": ("left_elbow", "right_elbow", "left_wrist", "right_wrist"),
}


def _model_path() -> str:
    models_dir = os.environ.get("MODELS_DIR", "models")
    return os.path.join(models_dir, "pose_landmarker_heavy.task")


@dataclass
class PoseFrame:
    image_shape: tuple  # (h, w)
    landmarks_px: dict  # name -> (x_px, y_px)
    visibility: dict    # name -> 0..1
    mask: object        # HxW float32 person-probability (numpy)
    detected: bool
    detect_conf: float


# ---------------------------------------------------------------------------
# Pose landmarking (lazy heavy imports)
# ---------------------------------------------------------------------------
def run_pose_landmarker(image_bgr, model_path: Optional[str] = None) -> PoseFrame:
    import numpy as np
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    model_path = model_path or _model_path()
    h, w = image_bgr.shape[:2]
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=model_path),
        running_mode=mp_vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_segmentation_masks=True,
    )
    landmarker = mp_vision.PoseLandmarker.create_from_options(options)
    try:
        result = landmarker.detect(mp_image)
    finally:
        landmarker.close()

    if not result.pose_landmarks:
        return PoseFrame((h, w), {}, {}, np.zeros((h, w), np.float32), False, 0.0)

    lm_list = result.pose_landmarks[0]
    landmarks_px, visibility = {}, {}
    for idx, name in {**_MP_TO_COCO, **_MP_EXTRA}.items():
        lm = lm_list[idx]
        landmarks_px[name] = (lm.x * w, lm.y * h)
        visibility[name] = float(getattr(lm, "visibility", 1.0))

    if result.segmentation_masks:
        mask = result.segmentation_masks[0].numpy_view().astype(np.float32)
    else:
        mask = np.zeros((h, w), np.float32)

    # detect confidence = mean visibility over the COCO-17 set only
    coco_vis = [visibility[n] for n in core.COCO_17 if n in visibility]
    detect_conf = float(sum(coco_vis) / len(coco_vis)) if coco_vis else 0.0
    return PoseFrame((h, w), landmarks_px, visibility, mask, True, detect_conf)


def estimate_pixel_height(frame: PoseFrame, mask_threshold: float = 0.5) -> Optional[float]:
    """Top-of-mask to lowest heel/ankle (MediaPipe has no head-top landmark)."""
    import numpy as np
    mask = np.asarray(frame.mask)
    while mask.ndim > 2:
        mask = mask[..., 0]
    ys, _ = np.where(mask > mask_threshold)
    if ys.size == 0:
        return None
    top_y = float(ys.min())
    ankle_ys = [frame.landmarks_px[k][1] for k in
                ("left_heel", "right_heel", "left_ankle", "right_ankle")
                if k in frame.landmarks_px]
    bottom_y = max(max(ankle_ys) if ankle_ys else float(ys.max()), float(ys.max()))
    return bottom_y - top_y


def _mean_y(frame: PoseFrame, *names: str) -> Optional[float]:
    vals = [frame.landmarks_px[n][1] for n in names if n in frame.landmarks_px]
    return (sum(vals) / len(vals)) if vals else None


def measurement_rows_y(frame: PoseFrame) -> dict:
    """Image-row (y px) to sample for each part, from landmark positions."""
    sh = _mean_y(frame, "left_shoulder", "right_shoulder")
    hip = _mean_y(frame, "left_hip", "right_hip")
    knee = _mean_y(frame, "left_knee", "right_knee")
    ankle = _mean_y(frame, "left_ankle", "right_ankle")
    elbow = _mean_y(frame, "left_elbow", "right_elbow")
    wrist = _mean_y(frame, "left_wrist", "right_wrist")

    rows: dict[str, float] = {}
    if sh is not None:
        rows["shoulder"] = sh
        if hip is not None:
            rows["chest"] = sh + 0.30 * (hip - sh)
            rows["waist"] = sh + 0.65 * (hip - sh)
    if hip is not None:
        rows["hip"] = hip + 0.06 * (hip - (sh or hip * 0.8))
    if hip is not None and knee is not None:
        rows["thigh"] = hip + 0.15 * (knee - hip)
    if knee is not None and ankle is not None:
        rows["calf"] = knee + 0.35 * (ankle - knee)
    if sh is not None and elbow is not None:
        rows["bicep"] = sh + 0.50 * (elbow - sh)
    if elbow is not None and wrist is not None:
        rows["forearm"] = elbow + 0.30 * (wrist - elbow)
    return rows


def mask_width_and_quality_at_row(frame: PoseFrame, row_y: float, part: str) -> Optional[tuple]:
    """
    Returns (width_px, quality) for the part's row, where quality is the fraction
    of the spanned pixels that are actually inside the mask (0..1) — a continuity
    signal that feeds the per-field confidence. Region isolation (torso vs limb)
    is salvaged from BodyProcessing.mask_width_at_row.
    """
    import numpy as np
    mask = np.asarray(frame.mask)
    while mask.ndim > 2:
        mask = mask[..., 0]
    img_h, img_w = frame.image_shape
    y = int(round(row_y))
    if y < 0 or y >= img_h:
        return None

    px = frame.landmarks_px
    def x(name):  # noqa: E306
        return px.get(name, (0, 0))[0]
    l_hip, r_hip = x("left_hip"), x("right_hip")
    l_sh, r_sh = x("left_shoulder"), x("right_shoulder")
    l_knee, r_knee = x("left_knee"), x("right_knee")

    min_x, max_x = 0, img_w
    if part in ("chest", "waist", "hip"):
        hip_min = min(l_hip, r_hip) if (l_hip > 0 and r_hip > 0) else 0
        hip_max = max(l_hip, r_hip) if (l_hip > 0 and r_hip > 0) else img_w
        sh_min = min(l_sh, r_sh) if (l_sh > 0 and r_sh > 0) else 0
        sh_max = max(l_sh, r_sh) if (l_sh > 0 and r_sh > 0) else img_w
        body_left = min([v for v in (hip_min, sh_min) if v > 0] or [0])
        body_right = max([v for v in (hip_max, sh_max) if v > 0] or [img_w])
        body_w = body_right - body_left
        if part == "chest":
            min_x, max_x = max(0, int(sh_min - body_w * 0.05)), min(img_w, int(sh_max + body_w * 0.05))
        elif part == "waist":
            min_x, max_x = max(0, int(hip_min - body_w * 0.15)), min(img_w, int(hip_max + body_w * 0.15))
        else:  # hip
            min_x, max_x = max(0, int(hip_min - body_w * 0.25)), min(img_w, int(hip_max + body_w * 0.25))
    elif part in ("bicep", "forearm"):
        arm_x = l_sh if l_sh > 0 else r_sh
        if arm_x > 0:
            r = int(img_w * 0.08)
            min_x, max_x = max(0, int(arm_x - r)), min(img_w, int(arm_x + r))
    elif part in ("thigh", "calf"):
        knee_x = l_knee if l_knee > 0 else r_knee
        if knee_x > 0:
            r = int(img_w * 0.14)
            min_x, max_x = max(0, int(knee_x - r)), min(img_w, int(knee_x + r))

    row = mask[y, min_x:max_x]
    active = np.where(row > 0.5)[0]
    if active.size == 0:
        return None
    span = float(active[-1] - active[0] + 1)
    quality = float(active.size / span) if span > 0 else 0.0
    return span, quality


# ---------------------------------------------------------------------------
# Orchestration -> the measurements slice + shape + ledger
# ---------------------------------------------------------------------------
def compute_measurements(
    image_bgr,
    declared_height_cm: float,
    declared_weight_kg: float,
    sex: int,
    declared_body_type: Optional[str] = None,
    model_path: Optional[str] = None,
) -> dict:
    """
    Returns a dict with keys: status, and on success `measurements`, `body_shape`,
    `accuracy_ledger`, `body_models` (assembled record with the measurements slice).
    """
    frame = run_pose_landmarker(image_bgr, model_path)
    if not frame.detected:
        return {"status": "error", "reason": "no_person_detected"}
    return measure_from_frame(frame, declared_height_cm, declared_weight_kg, sex, declared_body_type)


def measure_from_frame(
    frame: PoseFrame,
    declared_height_cm: float,
    declared_weight_kg: float,
    sex: int,
    declared_body_type: Optional[str] = None,
) -> dict:
    """Measure from an ALREADY-detected pose frame (lets the caller gate first, and lets
    the capture session reuse one pose pass per photo). Same contract as compute_measurements."""
    px_height = estimate_pixel_height(frame)
    scale = core.scale_from_pixel_height(px_height, declared_height_cm)  # declared height anchor
    if scale is None:
        return {"status": "error", "reason": "could_not_calibrate_scale"}

    rows = measurement_rows_y(frame)

    # 1) widths (cm) + mask quality per row
    widths_cm, quality = {}, {}
    for part, row_y in rows.items():
        got = mask_width_and_quality_at_row(frame, row_y, part)
        if got is not None:
            w_px, q = got
            widths_cm[part] = w_px / scale
            quality[part] = q

    # 2) anatomical guardrail (salvaged): forearm never wider than bicep
    if "bicep" in widths_cm and "forearm" in widths_cm and widths_cm["forearm"] > widths_cm["bicep"]:
        widths_cm["forearm"] = widths_cm["bicep"] * 0.90

    # 3) circumference (front-only depth estimate) + per-field confidence
    measurements = {}
    for part, w_cm in widths_cm.items():
        depth_cm = core.estimate_depth_cm(part, w_cm, sex)
        circ = core.ellipse_circumference(w_cm, depth_cm)
        lm_vis = min((frame.visibility.get(n, 0.0) for n in _PART_LANDMARKS.get(part, ())), default=0.0)
        conf = core.part_confidence(
            landmark_visibility=lm_vis,
            mask_quality=quality.get(part, 0.0),
            depth_measured=False,  # front-only slice-2; side photo -> True later
            plausibility=core.plausibility_factor(part, circ),
        )
        measurements[part] = {
            "width_cm": round(w_cm, 1),
            "depth_cm": round(depth_cm, 1),
            "circumference_cm": round(circ, 1),
            "depth_source": "estimated_no_depth",
            "confidence": conf,
        }

    # 4) computed shape (source of truth) + declared cross-check (never overrides)
    shape = core.classify_body_shape(measurements, sex)
    crosscheck = core.crosscheck_body_type(declared_body_type, shape)

    # 5) coverage + backend accuracy ledger (§6)
    coverage = core.landmark_coverage(frame.visibility)
    ledger = core.build_accuracy_ledger(measurements, coverage, crosscheck, frame.detect_conf)

    body_shape = {**shape, "declared_crosscheck": crosscheck,
                  "bmi": round(declared_weight_kg / ((declared_height_cm / 100) ** 2), 1)
                  if declared_height_cm else None}

    return {
        "status": "ok",
        "scale_px_per_cm": round(scale, 3),
        "measurements": measurements,
        "body_shape": body_shape,
        "accuracy_ledger": ledger,
        "body_models": assemble_body_models(
            measurements=measurements, body_shape=body_shape, accuracy_ledger=ledger),
    }
