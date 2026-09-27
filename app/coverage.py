"""
Photo -> renderable cloth_types ("detect, don't demand").

CatVTON can only place a garment on a body region that's actually in the frame (the AutoMasker
needs it). So instead of demanding the user upload the "right" photo, we detect what their photo
supports and only offer those garments — better UX (lazy first taste) AND better renders (no
photo<->garment mismatch, which caused the earlier "buggy lower part" failures).

Reuses the CPU MediaPipe pose landmarker already on Service A (app/measurements.py) — no new deps,
no GPU. Degrades OPEN: if pose detection is unavailable, allow all types rather than block.

Rules (visibility >= 0.5):
  upper   = a shoulder is visible           (torso in frame)
  lower   = a hip AND a knee are visible     (legs in frame)
  overall = a shoulder AND a hip AND (knee or ankle) visible   (~full body, for dresses)
"""
from __future__ import annotations

VIS = 0.5
CLOTH_TYPES = ("upper", "lower", "overall")


def analyze_coverage(image_bgr) -> dict:
    """Return {allowed:[...], coverage:{upper,lower,overall}, detected:bool, hint:str}."""
    try:
        from app import measurements as body
        frame = body.run_pose_landmarker(image_bgr)
    except Exception:
        # pose stack unavailable -> degrade open so the user is never blocked
        return {"allowed": list(CLOTH_TYPES), "detected": False,
                "coverage": {t: True for t in CLOTH_TYPES},
                "hint": "Showing everything (couldn't run fit detection)."}

    if not getattr(frame, "detected", False):
        return {"allowed": [], "detected": False,
                "coverage": {t: False for t in CLOTH_TYPES},
                "hint": "Couldn't spot you — try a clear, well-lit photo, ideally head-to-knees."}

    vis = frame.visibility or {}

    def seen(*names):
        return any(vis.get(n, 0.0) >= VIS for n in names)

    upper_ok = seen("left_shoulder", "right_shoulder")
    hips_ok = seen("left_hip", "right_hip")
    knees_ok = seen("left_knee", "right_knee")
    ankles_ok = seen("left_ankle", "right_ankle")

    coverage = {
        "upper": upper_ok,
        "lower": hips_ok and knees_ok,
        "overall": upper_ok and hips_ok and (knees_ok or ankles_ok),
    }
    allowed = [t for t in CLOTH_TYPES if coverage[t]]

    if not allowed:
        hint = "Couldn't read your body — try a clearer photo."
    elif allowed == ["upper"]:
        hint = "Great for tops. Add a full-body photo (head to knees) to unlock bottoms & dresses."
    elif "overall" not in coverage or not coverage["overall"]:
        hint = "Add a full-body photo to unlock dresses."
    else:
        hint = "Full body detected — everything's unlocked."
    return {"allowed": allowed, "detected": True, "coverage": coverage, "hint": hint}
