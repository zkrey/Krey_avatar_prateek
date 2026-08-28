"""
Capture-session pipeline — turns N photos of a capture into ONE consolidated twin for
the user, routed through the deterministic `capture_core` brain.

Flow (heavy deps lazy; GPU-free CPU inference):
  1. detect every face per photo (InsightFace/ArcFace) -> embedding + bbox + age + date
  2. cluster identities, pick the USER cluster (recurs across the most dates)
  3. per user-face frame: crop and read the face attributes via the face pipeline
  4. aggregate: identity confidence + soft-confirm decision; appearance fused with the
     right strategy per attribute (eye/skin stable; hair/build recency-weighted)

Model: InsightFace `buffalo_l` (research/non-commercial — see docs/scope_bakeins.md;
swap for a licence-cleared model before commercial launch). Auto-downloads on first use.
`capture_core` holds all the maths and is tested without any of this.
"""
from __future__ import annotations
from typing import List, Optional
import os

from app import capture_core as cc
from app import face
from app import face_pipeline as fp

# attribute -> aggregation strategy: identity-stable vs. time-varying (recency-weighted)
_ATTR_MODE = {"skin_tone": "stable", "eye_colour": "stable",
              "hair_colour": "recent", "hair_texture": "recent"}

_analysis_app = None


def _get_app(det_size: int = 1024):
    """Lazily build (and cache) the InsightFace analyzer on CPU."""
    global _analysis_app
    if _analysis_app is None:
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(det_size, det_size))
        _analysis_app = app
    return _analysis_app


def _exif_datetime(path: str) -> Optional[str]:
    try:
        from PIL import Image
        ex = Image.open(path).getexif()
        for tag in (36867, 306):    # DateTimeOriginal, DateTime
            if ex.get(tag):
                return str(ex.get(tag))
    except Exception:
        return None
    return None


def _attributes_for_crop(crop_bgr) -> Optional[dict]:
    """Run the face attribute pipeline on a single-face crop -> body_models face slices."""
    # identity is already resolved and the crop is centred on the known user, so a
    # bystander caught in the padding must not veto the read -> enforce_single=False.
    sig = fp.sample_face(crop_bgr, enforce_single=False)
    if sig["n_faces"] == 0:
        return None
    feats = (face.hair.texture_features_from_region(sig["hair_region"])
             if sig["hair_region"] is not None else None)
    return face.assemble_face(skin_samples=sig["skin_samples"] or None,
                              hair_samples=sig["hair_samples"] or None,
                              iris_samples=sig["iris_samples"] or None,
                              hair_features=feats)


def analyze_capture(image_paths: List[str], read_attributes: bool = True,
                    max_frames: int = 8) -> dict:
    """
    Consolidate a capture session into one user profile. Returns:
      {decision, identity, timeline, appearance, frames}
    `read_attributes=False` skips the per-frame attribute extraction (identity + timeline
    only) — useful for a fast 'is this a consistent person?' gate before the heavy read.
    """
    import cv2
    app = _get_app()

    faces = []   # one row per detected face
    for path in sorted(image_paths):
        img = cv2.imread(path)
        if img is None:
            continue
        H, W = img.shape[:2]
        d = cc.parse_capture_date(_exif_datetime(path), os.path.basename(path))
        for f in app.get(img):
            x0, y0, x1, y1 = [int(v) for v in f.bbox]
            faces.append({
                "photo": os.path.basename(path), "date": d,
                "emb": [float(v) for v in f.normed_embedding],
                "age": int(f.age), "det": float(f.det_score),
                "bbox": (x0, y0, x1, y1), "shape": (H, W), "img": img,
            })

    if not faces:
        return {"decision": "retake_no_face", "identity": None,
                "timeline": None, "appearance": None, "frames": []}

    labels = cc.cluster_by_similarity([f["emb"] for f in faces])
    user_c = cc.select_user_cluster(labels, [f["date"] for f in faces])
    members = cc.members_by_cluster(labels)
    user_idx = members[user_c]

    dates = [faces[i]["date"] for i in user_idx]
    known = sorted(d for d in dates if d)
    intra = cc.intra_similarities([f["emb"] for f in faces], user_idx)
    ident = cc.identity_confidence(intra, n_frames=len(user_idx), n_dates=len(set(known)))
    decision = cc.capture_decision(ident["overall"], len(user_idx))

    # Auto-pick the owner's best frames for the expensive attribute reads, so a lazy album
    # dump (dozens of the user's photos) reduces to a strong handful. Identity/timeline keep
    # ALL the owner's evidence above; only extraction runs on the selection.
    def _q(i):
        (x0, y0, x1, y1), (H, W) = faces[i]["bbox"], faces[i]["shape"]
        return faces[i]["det"] * ((x1 - x0) * (y1 - y0)) / float(max(1, H * W))
    picks = cc.select_best_frames(
        [{"index": i, "quality": _q(i), "date": faces[i]["date"]} for i in user_idx],
        target=max_frames)

    timeline = {
        "oldest": known[0] if known else None,
        "newest": known[-1] if known else None,
        "n_dated": len(known),
        "n_undated": len(dates) - len(known),
        "age_estimates": [faces[i]["age"] for i in user_idx],   # noisy cross-check only
    }

    frames, per_attr = [], {k: [] for k in _ATTR_MODE}
    if read_attributes:
        for i in picks:
            f = faces[i]
            x0, y0, x1, y1 = f["bbox"]; H, W = f["shape"]
            pad = int(0.6 * max(x1 - x0, y1 - y0))       # include hair + a margin
            crop = f["img"][max(0, y0 - pad):min(H, y1 + pad), max(0, x0 - pad):min(W, x1 + pad)]
            rec = _attributes_for_crop(crop) if crop.size else None
            slot = {"photo": f["photo"], "date": f["date"], "read": rec is not None}
            if rec:
                for attr in _ATTR_MODE:
                    node = rec.get(attr) or {}
                    # skin fuses on the CONTINUOUS tone so a real sub-bucket difference
                    # survives; the per-frame slot still shows the friendly bucket.
                    agg_val = node.get("monk_continuous") if attr == "skin_tone" else node.get("value")
                    slot[attr] = node.get("value")
                    per_attr[attr].append({"value": agg_val, "confidence": node.get("confidence") or 0.0,
                                           "date": f["date"]})
            frames.append(slot)

    appearance = {}
    for attr, mode in _ATTR_MODE.items():
        obs = per_attr[attr]
        d = [o["date"] for o in obs]
        if attr == "skin_tone":
            appearance[attr] = cc.aggregate_numeric(obs, mode="stable")   # continuous Monk tone
        elif mode == "recent":
            appearance[attr] = cc.aggregate_categorical(obs, mode="recent", dates=d)
        else:
            appearance[attr] = cc.aggregate_categorical(obs, mode="stable")

    return {
        "decision": decision,
        "identity": ident,
        "timeline": timeline,
        "appearance": appearance,
        "frames": frames,
        "n_faces_total": len(faces),
        "n_user_faces": len(user_idx),
        # owner-only retention: only the owner is profiled; everyone else in the pile is
        # never returned and is discarded with the raw pixels. Auto-select trims the owner's
        # own frames to the best few actually read.
        "retention": {
            "owner_faces": len(user_idx),
            "owner_faces_used": len(picks),
            "other_faces_discarded": len(faces) - len(user_idx),
            "policy": "owner-only",
        },
    }
