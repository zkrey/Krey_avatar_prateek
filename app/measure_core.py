"""
Body-measurement core — the deterministic heart of Service A, slice 2.

No ML, no GPU, no image libraries: this module is pure Python stdlib so the whole
measurement contract (scale, circumference, per-field confidence, the declared
body-type cross-check, and the accuracy ledger) is unit-testable without a photo
or the pose model. It mirrors how `monk.py` is the tested core of slice 1.

The image pipeline (MediaPipe pose landmarker + segmentation mask -> pixel widths)
lives in `app/measurements.py` and feeds numbers into the functions here.

Salvage note: the measurement algorithm (height as scale anchor, landmark-derived
sample rows, Ramanujan ellipse circumference, population depth ratios, anatomical
guardrails, body-shape taxonomy) is adapted from the departed engineer's
`zkrey/UserImageProcessingAPI` (ProcessingSteps/BodyProcessing.py). What this file
ADDS on top, per the Capture Pipeline Spec: the COCO-17 landmark contract and
landmark_coverage, a numeric per-field confidence, the declared body_type
cross-check (cross-check only — never source of truth), and the §6 backend
accuracy ledger.
"""
from __future__ import annotations
from typing import Optional, Mapping, Sequence
import math

MODEL_TAG = "rule-measure-v0"
SCHEMA_VERSION = "body_models-0.2.0"

# ---------------------------------------------------------------------------
# The 17 body landmarks. The Capture Pipeline Spec numbers landmarks LM 0..16
# (COCO-17 convention). MediaPipe's pose model uses a different 33-point index,
# so the pipeline maps MediaPipe -> these names before computing coverage.
# ---------------------------------------------------------------------------
COCO_17 = (
    "nose",            # 0
    "left_eye",        # 1
    "right_eye",       # 2
    "left_ear",        # 3
    "right_ear",       # 4
    "left_shoulder",   # 5
    "right_shoulder",  # 6
    "left_elbow",      # 7
    "right_elbow",     # 8
    "left_wrist",      # 9
    "right_wrist",     # 10
    "left_hip",        # 11
    "right_hip",       # 12
    "left_knee",       # 13
    "right_knee",      # 14
    "left_ankle",      # 15
    "right_ankle",     # 16
)

# Population depth ratios (depth = width * ratio) for the front-only estimate,
# keyed by sex ("1" male, "2" female). Salvaged from BodyProcessing.py.
DEFAULT_DEPTH_RATIO: dict[str, dict[str, float]] = {
    "1": {"shoulder": 0.50, "chest": 0.78, "waist": 0.82, "hip": 0.82,
          "thigh": 0.92, "calf": 0.85, "bicep": 0.90, "forearm": 0.85},
    "2": {"shoulder": 0.45, "chest": 0.72, "waist": 0.78, "hip": 0.85,
          "thigh": 0.90, "calf": 0.85, "bicep": 0.90, "forearm": 0.85},
}

# Rough adult plausibility ranges (cm) — used only to DAMP confidence for absurd
# readings, never to reject. Wide on purpose to avoid over-flagging real bodies.
PLAUSIBLE_CIRC_CM: dict[str, tuple[float, float]] = {
    "shoulder": (70.0, 140.0),
    "chest":    (60.0, 140.0),
    "waist":    (45.0, 150.0),
    "hip":      (65.0, 150.0),
    "thigh":    (30.0, 90.0),
    "calf":     (20.0, 60.0),
    "bicep":    (15.0, 55.0),
    "forearm":  (13.0, 45.0),
}

# Confidence weight of each part in the aggregate body confidence. Torso parts
# drive garment fit hardest, so they count most.
PART_WEIGHT: dict[str, float] = {
    "shoulder": 1.0, "chest": 1.0, "waist": 1.0, "hip": 1.0,
    "thigh": 0.6, "calf": 0.4, "bicep": 0.4, "forearm": 0.4,
}

# Canonical body-shape families + synonyms, so a free-text declared body_type can
# be compared with the computed shape without being treated as source of truth.
_SHAPE_SYNONYMS: dict[str, str] = {
    "hourglass": "hourglass",
    "pear": "triangle", "triangle": "triangle", "spoon": "triangle",
    "apple": "round", "round": "round", "oval": "round",
    "rectangle": "rectangle", "straight": "rectangle", "banana": "rectangle",
    "inverted triangle": "inverted_triangle", "inverted": "inverted_triangle",
    "trapezoid": "inverted_triangle", "v-shape": "inverted_triangle", "v shape": "inverted_triangle",
}


# ---------------------------------------------------------------------------
# Scale anchor + geometry
# ---------------------------------------------------------------------------
def scale_from_pixel_height(pixel_height: float, declared_height_cm: float) -> Optional[float]:
    """px_per_cm from the DECLARED height (the spec's scale anchor)."""
    if not pixel_height or pixel_height <= 0:
        return None
    if not declared_height_cm or declared_height_cm <= 0:
        return None
    return pixel_height / declared_height_cm


def ellipse_circumference(width_cm: float, depth_cm: float) -> float:
    """Ramanujan's 2nd approximation for an ellipse of the given axes."""
    a, b = width_cm / 2.0, depth_cm / 2.0
    if a <= 0 or b <= 0:
        return 0.0
    h = ((a - b) ** 2) / ((a + b) ** 2)
    return math.pi * (a + b) * (1 + (3 * h) / (10 + math.sqrt(4 - 3 * h)))


def estimate_depth_cm(part: str, width_cm: float, sex: int) -> float:
    """Population-ratio depth for the front-only case."""
    ratios = DEFAULT_DEPTH_RATIO.get(str(sex), DEFAULT_DEPTH_RATIO["2"])
    return width_cm * ratios.get(part, 0.85)


# ---------------------------------------------------------------------------
# Per-field confidence
# ---------------------------------------------------------------------------
def plausibility_factor(part: str, circumference_cm: float) -> float:
    """1.0 inside the plausible range; decays smoothly outside it (never 0)."""
    lo, hi = PLAUSIBLE_CIRC_CM.get(part, (0.0, float("inf")))
    if lo <= circumference_cm <= hi:
        return 1.0
    span = (hi - lo) if hi != float("inf") else max(lo, 1.0)
    dist = (lo - circumference_cm) if circumference_cm < lo else (circumference_cm - hi)
    # 1 span outside -> ~0.5, 2 spans -> ~0.33, etc. Floor at 0.1.
    return max(0.1, 1.0 / (1.0 + dist / max(span, 1.0)))


def part_confidence(
    landmark_visibility: float,
    mask_quality: float,
    depth_measured: bool,
    plausibility: float,
) -> float:
    """
    Numeric 0..1 confidence for a single measurement, blending:
      - landmark_visibility: min visibility of the landmarks bounding the row,
      - mask_quality: how cleanly the segmentation row was filled (0..1),
      - depth source: a real side-photo depth beats a population ratio,
      - plausibility: whether the circumference sits in a human range.
    """
    v = _clamp01(landmark_visibility)
    m = _clamp01(mask_quality)
    depth_factor = 1.0 if depth_measured else 0.75
    p = _clamp01(plausibility)
    conf = v * m * depth_factor * p
    return round(_clamp(conf, 0.05, 0.99), 3)


# ---------------------------------------------------------------------------
# Body shape (computed = source of truth) + declared cross-check
# ---------------------------------------------------------------------------
def classify_body_shape(measurements: Mapping[str, Mapping[str, float]], sex: int) -> dict:
    """
    Computed body shape from circumferences. Adapted from BodyProcessing.py.
    `measurements[part]` must expose "circumference_cm" (and "width_cm" for shoulder).
    """
    def circ(part: str) -> Optional[float]:
        m = measurements.get(part)
        return m.get("circumference_cm") if m else None

    top = circ("chest")
    waist = circ("waist")
    hip = circ("hip")
    shoulder_w = (measurements.get("shoulder") or {}).get("width_cm")

    if waist is None or hip is None or (top is None and shoulder_w is None):
        return {"shape": "insufficient_data", "family": None,
                "reason": "missing chest/waist/hip measurement"}

    if top is None:
        top = shoulder_w * 2.5  # rough girth proxy when chest is missing

    if sex == 2:  # female taxonomy
        bust_hip_diff = abs(top - hip) / max(top, hip)
        waist_drop_bust = (top - waist) / top if top else 0
        waist_drop_hip = (hip - waist) / hip if hip else 0
        if bust_hip_diff < 0.05 and waist_drop_bust > 0.25 and waist_drop_hip > 0.25:
            shape = "Hourglass"
        elif hip > top * 1.05 and waist_drop_hip > 0.20:
            shape = "Pear / Triangle"
        elif top > hip * 1.05:
            shape = "Inverted Triangle"
        elif waist > top * 0.95 and waist > hip * 0.95:
            shape = "Apple / Round"
        else:
            shape = "Rectangle / Straight"
    else:  # male taxonomy
        shoulder_drop_waist = (top - waist) / top if top else 0
        if shoulder_drop_waist > 0.15 and top > hip * 1.05:
            shape = "Trapezoid (V-shape)"
        elif top > hip * 1.1 and waist < top * 0.9:
            shape = "Inverted Triangle"
        elif waist > top * 0.98 and waist > hip * 0.98:
            shape = "Oval / Round"
        elif hip > top:
            shape = "Triangle"
        else:
            shape = "Rectangle"

    return {
        "shape": shape,
        "family": _shape_family(shape),
        "inputs_used": {"top_girth_cm": round(top, 1),
                        "waist_cm": round(waist, 1), "hip_cm": round(hip, 1)},
    }


def crosscheck_body_type(declared_body_type: Optional[str], computed_shape: Mapping) -> dict:
    """
    Compare the user's DECLARED body_type against the computed shape. The declared
    value is a cross-check only — it never overrides the computed measurement.
    Returns agreement (True/False/None) and a note; a mismatch is a confidence
    signal handled by the ledger, not a reason to change the numbers.
    """
    computed_family = (computed_shape or {}).get("family")
    declared_family = _shape_family(declared_body_type) if declared_body_type else None

    if declared_family is None or computed_family is None:
        agreement: Optional[bool] = None
        note = "no declared body_type" if declared_family is None else "shape not computable"
    else:
        agreement = declared_family == computed_family
        note = "declared matches computed" if agreement else "declared differs from computed"

    return {
        "declared_body_type": declared_body_type,
        "declared_family": declared_family,
        "computed_shape": (computed_shape or {}).get("shape"),
        "computed_family": computed_family,
        "agreement": agreement,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Landmark coverage + the backend accuracy ledger (spec §6)
# ---------------------------------------------------------------------------
def landmark_coverage(visibilities: Mapping[str, float], min_visibility: float = 0.5) -> dict:
    """Fraction of the 17 COCO landmarks detected at >= min_visibility."""
    detected = [n for n in COCO_17 if visibilities.get(n, 0.0) >= min_visibility]
    return {
        "detected": len(detected),
        "total": len(COCO_17),
        "coverage": round(len(detected) / len(COCO_17), 3),
        "missing": [n for n in COCO_17 if n not in detected],
    }


# Landmarks that must be visible for a measurable STANDING body (head-to-ankle).
_BODY_ESSENTIAL = ("left_shoulder", "right_shoulder", "left_hip", "right_hip",
                   "left_knee", "right_knee", "left_ankle", "right_ankle")


def body_measurable(visibilities: Mapping[str, float], min_visibility: float = 0.5,
                    min_essential: int = 7) -> dict:
    """
    Body analog of the single-face gate: is this a clean full standing body we can
    measure, or a headshot / half-body / occluded frame we should skip? Requires the
    torso-to-ankle landmarks (shoulders, hips, knees, ankles) — a face-only or
    waist-up frame has no legs and can't be scaled or measured below the waist.
    """
    present = [n for n in _BODY_ESSENTIAL if visibilities.get(n, 0.0) >= min_visibility]
    cov = landmark_coverage(visibilities, min_visibility)
    measurable = len(present) >= min_essential
    return {
        "measurable": measurable,
        "reason": "ok" if measurable else "incomplete_body",   # not a full standing body
        "essential_present": len(present),
        "essential_total": len(_BODY_ESSENTIAL),
        "coverage": cov["coverage"],
    }


def build_accuracy_ledger(
    measurements: Mapping[str, Mapping],
    coverage: Mapping,
    body_type_check: Mapping,
    detect_confidence: float,
) -> dict:
    """
    The backend accuracy ledger (Capture Pipeline Spec §6). Never surfaced to the
    user — it drives re-capture nudges and downstream fit scoring. Records per-field
    confidence, landmark coverage, an aggregate body confidence, and flags. A
    declared/computed body-type mismatch dents confidence but never edits a number.
    """
    weighted, wsum = 0.0, 0.0
    low_fields: list[str] = []
    for part, m in measurements.items():
        conf = float(m.get("confidence", 0.0))
        w = PART_WEIGHT.get(part, 0.5)
        weighted += conf * w
        wsum += w
        if conf < 0.50:
            low_fields.append(part)

    body_conf = (weighted / wsum) if wsum else 0.0
    # Coverage gates the whole reading: the spec wants all 17 landmarks for the mesh.
    body_conf *= (0.5 + 0.5 * float(coverage.get("coverage", 0.0)))

    mismatch = body_type_check.get("agreement") is False
    if mismatch:
        body_conf *= 0.9  # a cross-check disagreement is a soft penalty only

    body_conf = round(_clamp(body_conf, 0.0, 0.99), 3)

    flags: list[str] = []
    if coverage.get("coverage", 0.0) < 1.0:
        flags.append("incomplete_landmarks")
    if low_fields:
        flags.append("low_confidence_fields")
    if mismatch:
        flags.append("body_type_mismatch")
    if body_conf < 0.60:
        flags.append("needs_recapture")  # spec §6: nudge if overall < 0.60

    return {
        "model": MODEL_TAG,
        "schema_version": SCHEMA_VERSION,
        "landmark_coverage": coverage.get("coverage", 0.0),
        "landmarks_detected": coverage.get("detected", 0),
        "detect_confidence": round(float(detect_confidence), 3),
        "per_field_confidence": {p: m.get("confidence") for p, m in measurements.items()},
        "low_confidence_fields": low_fields,
        "body_type_crosscheck": body_type_check,
        "body_confidence": body_conf,           # aggregate, backend-only
        "surfaced_to_user": False,              # invariant: never shown
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _shape_family(shape: Optional[str]) -> Optional[str]:
    if not shape:
        return None
    s = shape.strip().lower()
    for key, fam in _SHAPE_SYNONYMS.items():
        if key in s:
            return fam
    return None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _clamp01(x: float) -> float:
    return _clamp(float(x), 0.0, 1.0)
