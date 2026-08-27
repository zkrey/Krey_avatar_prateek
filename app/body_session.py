"""
Body-capture session — consolidate the 8 body measurements for the identified user across
several full-body frames, the build counterpart of the face capture session.

Unlike face (which aggregates fine from casual photos), BUILD cannot be salvaged from group
/ distant / half-body shots — measured directly, those gave 85-140 cm shoulder swings. So
each frame is gated (`measure_core.body_measurable`: a clean full standing body), and only
measurable frames feed the reconciliation. Build also DRIFTS with time, so measurements are
fused RECENCY-weighted (the freshest capture anchors the current build) and outlier-robust
(one bad frame can't drag a girth), reusing the tested numeric aggregator.

The reconciliation + decision are pure (tested without a model); the pose pass is lazy.
Declared height is the scale anchor — without it there is no absolute size.
"""
from __future__ import annotations
from typing import List, Optional, Sequence, Mapping
from app import capture_core as cc
from app import measure_core as core

# soft-confirm ladder for the body capture (mirrors the face one)
ACCEPT_FRAMES = 3
RECONFIRM_FRAMES = 1


def reconcile_measurements(frames: Sequence[Mapping], mode: str = "recent") -> dict:
    """
    Fuse per-frame measurements into one consolidated set. `frames` = [{date, measurements}]
    where measurements[part] = {circumference_cm, confidence, ...}. Each girth is fused with
    the recency-weighted, outlier-robust numeric aggregator; confidence falls as the frames
    disagree (relative spread). Pure.
    """
    all_parts: set = set()
    for f in frames:
        all_parts |= set(f.get("measurements", {}))

    out: dict = {}
    for part in sorted(all_parts):
        obs, dates = [], []
        for f in frames:
            m = (f.get("measurements") or {}).get(part)
            if m and m.get("circumference_cm") is not None:
                obs.append({"value": float(m["circumference_cm"]),
                            "confidence": float(m.get("confidence", 0.5)),
                            "date": f.get("date")})
                dates.append(f.get("date"))
        if not obs:
            continue
        agg = (cc.aggregate_numeric(obs, mode="recent", dates=dates)
               if mode == "recent" else cc.aggregate_numeric(obs, mode="stable"))
        if not agg:
            continue
        value = agg["value"]
        rel_spread = agg["spread"] / value if value else 1.0
        mean_conf = sum(o["confidence"] for o in obs) / len(obs)
        confidence = round(max(0.30, min(0.95, mean_conf * (1.0 - min(1.0, rel_spread)))), 3)
        out[part] = {
            "circumference_cm": round(value, 1),
            "confidence": confidence,
            "spread_cm": round(agg["spread"], 1),
            "n_frames": agg["n_frames"],
            "n_dropped_outliers": agg["n_dropped_outliers"],
            "needs_confirm": rel_spread > 0.12,          # >12% disagreement across frames
        }
    return out


def select_pose_for_face(head_points: Sequence, face_bbox) -> Optional[int]:
    """
    Pure: pick the pose whose head sits in the user's face box (identity-anchored body
    measurement in a group frame). head_points = per-pose (x,y) head/nose positions;
    face_bbox = (x0,y0,x1,y1) of the user's matched face. Prefer a head inside the box;
    else the nearest head within one box-width; else None (user's body not found).
    """
    if not head_points or face_bbox is None:
        return None
    x0, y0, x1, y1 = face_bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    box_w = max(1.0, x1 - x0)
    inside, nearest, nearest_d = [], None, None
    for i, (hx, hy) in enumerate(head_points):
        if x0 <= hx <= x1 and y0 <= hy <= y1:
            inside.append((i, (hx - cx) ** 2 + (hy - cy) ** 2))
        d = ((hx - cx) ** 2 + (hy - cy) ** 2) ** 0.5
        if nearest_d is None or d < nearest_d:
            nearest, nearest_d = i, d
    if inside:
        return min(inside, key=lambda t: t[1])[0]
    if nearest_d is not None and nearest_d <= 1.5 * box_w:
        return nearest
    return None


def body_capture_decision(n_measurable: int, body_confidence: float) -> str:
    """Soft-confirm ladder: retake only when there's no usable full-body frame."""
    if n_measurable <= 0:
        return "retake_no_body"
    if n_measurable >= ACCEPT_FRAMES and body_confidence >= 0.60:
        return "accept"
    if n_measurable >= RECONFIRM_FRAMES:
        return "reconfirm"
    return "retake_low_confidence"


def analyze_body(
    image_paths: List[str],
    declared_height_cm: float,
    declared_weight_kg: float,
    sex: int,
    declared_body_type: Optional[str] = None,
    model_path: Optional[str] = None,
    user_reference: Optional[Sequence[float]] = None,
) -> dict:
    """
    Consolidate build across full-body frames. Returns:
      {decision, n_frames_total, n_measurable, timeline, measurements, body_shape,
       accuracy_ledger, per_frame}
    Height is the scale anchor. Non-measurable frames (headshots, half-body) are gated out.
    With `user_reference` (the user's face embedding), a group frame is IDENTITY-ANCHORED:
    the user's face is located and the pose whose head sits there is measured, instead of
    whoever is most prominent. Without it, the single most-prominent pose is used.
    """
    import os
    import cv2
    from app import measurements as body

    per_frame, good = [], []
    for path in sorted(image_paths):
        img = cv2.imread(path)
        if img is None:
            continue
        date = cc.parse_capture_date(_exif_datetime(path), os.path.basename(path))
        frame, anchor_note = _pose_for_user(img, model_path, user_reference, body)
        gate = core.body_measurable(frame.visibility) if (frame and frame.detected) else \
            {"measurable": False, "reason": anchor_note or "no_person_detected", "coverage": 0.0}
        row = {"photo": os.path.basename(path), "date": date,
               "measurable": gate["measurable"], "reason": gate["reason"],
               "coverage": gate["coverage"], "anchored": bool(user_reference)}
        if gate["measurable"]:
            res = body.measure_from_frame(frame, declared_height_cm, declared_weight_kg,
                                          sex, declared_body_type)
            if res["status"] == "ok":
                row["measurements"] = res["measurements"]
                row["_shape"] = res["body_shape"]
                good.append(row)
        per_frame.append(row)

    dates = [g["date"] for g in good]
    known = sorted(d for d in dates if d)
    measurements = reconcile_measurements(good, mode="recent") if good else {}

    # shape + ledger from the CONSOLIDATED measurements (computed = source of truth)
    body_shape = core.classify_body_shape(measurements, sex) if measurements else None
    if body_shape is not None:
        crosscheck = core.crosscheck_body_type(declared_body_type, body_shape)
        body_shape = {**body_shape, "declared_crosscheck": crosscheck,
                      "bmi": round(declared_weight_kg / ((declared_height_cm / 100) ** 2), 1)
                      if declared_height_cm else None}
        cov = {"coverage": min(1.0, len(measurements) / 8), "detected": len(measurements)}
        ledger = core.build_accuracy_ledger(measurements, cov, crosscheck,
                                            detect_confidence=len(good) / max(1, len(per_frame)))
    else:
        ledger = None

    body_conf = ledger["body_confidence"] if ledger else 0.0
    return {
        "decision": body_capture_decision(len(good), body_conf),
        "n_frames_total": len(per_frame),
        "n_measurable": len(good),
        "timeline": {"oldest": known[0] if known else None,
                     "newest": known[-1] if known else None, "n_dated": len(known)},
        "measurements": measurements,
        "body_shape": body_shape,
        "accuracy_ledger": ledger,
        "per_frame": per_frame,
    }


def _pose_for_user(img, model_path, user_reference, body):
    """
    Return (pose_frame, note). Without a reference: the single most-prominent pose. With
    one: find the user's face, then the pose whose head sits there. note explains a miss
    (user not in frame / their pose not found) so the per-frame row can show why.
    """
    if user_reference is None:
        return body.run_pose_landmarker(img, model_path), None

    from app import identity
    face = identity.find_user_face(img, user_reference)
    if face is None:
        return None, "user_not_in_frame"
    poses = body.run_pose_landmarker_multi(img, model_path=model_path)
    if not poses:
        return None, "no_person_detected"
    heads = [p.landmarks_px.get("nose", (0.0, 0.0)) for p in poses]
    idx = select_pose_for_face(heads, face["bbox"])
    if idx is None:
        return None, "user_body_not_found"
    return poses[idx], None


def _exif_datetime(path: str) -> Optional[str]:
    try:
        from PIL import Image
        ex = Image.open(path).getexif()
        for tag in (36867, 306):
            if ex.get(tag):
                return str(ex.get(tag))
    except Exception:
        return None
    return None
