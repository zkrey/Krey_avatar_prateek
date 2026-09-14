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
import logging
import os

from app import capture_core as cc
from app import face
from app import face_pipeline as fp

log = logging.getLogger("krey.capture")

# attribute -> aggregation strategy: identity-stable vs. time-varying (recency-weighted)
_ATTR_MODE = {"skin_tone": "stable", "eye_colour": "stable",
              "hair_colour": "recent", "hair_texture": "recent"}

_analysis_app = None


def _get_app(det_size: int = None):
    """Lazily build (and cache) the InsightFace analyzer on CPU.

    Model + detection size are env-driven so the service fits small hosts: the default
    is `buffalo_s` (a MobileFaceNet pack, ~15 MB recogniser) at 640px, which keeps the
    resident footprint under a 1 GB cap — `buffalo_l` (ResNet50 ArcFace) + a 1024 det
    size OOM-kills a 1 GB container at model load. On a larger host set
    KREY_FACE_MODEL=buffalo_l (and rebuild so the image pre-warms it) for best accuracy.
    """
    global _analysis_app
    if _analysis_app is None:
        import os
        from insightface.app import FaceAnalysis
        model = os.environ.get("KREY_FACE_MODEL") or "buffalo_s"
        ds = det_size or int(os.environ.get("KREY_DET_SIZE") or "640")
        app = FaceAnalysis(name=model, providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(ds, ds))
        _analysis_app = app
    return _analysis_app


def release_app():
    """Drop the cached InsightFace analyzer to free its onnxruntime sessions (~200 MB).
    Called before the pose pass on a small host so identity + pose don't both sit resident;
    it rebuilds lazily on the next /capture/session."""
    global _analysis_app
    _analysis_app = None
    try:
        import gc
        gc.collect()
    except Exception:
        pass


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


def _owner_thumb(faces, idxs, max_px: int = 220) -> Optional[str]:
    """A small base64 JPEG crop of the owner's best face, for the user to confirm identity.
    Best-effort: returns None if it can't be produced. Not persisted (derive-and-discard)."""
    try:
        import base64
        import cv2
        # best available owner face: highest det_score among the given indices
        i = max(idxs, key=lambda j: faces[j].get("det", 0.0))
        f = faces[i]
        x0, y0, x1, y1 = f["bbox"]; H, W = f["shape"]
        pad = int(0.45 * max(x1 - x0, y1 - y0))          # include hair + a little margin
        crop = f["img"][max(0, y0 - pad):min(H, y1 + pad), max(0, x0 - pad):min(W, x1 + pad)]
        if not getattr(crop, "size", 0):
            return None
        ch, cw = crop.shape[:2]
        s = min(1.0, max_px / float(max(ch, cw)))
        if s < 1.0:
            crop = cv2.resize(crop, (max(1, int(cw * s)), max(1, int(ch * s))))
        ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception:
        return None


def analyze_capture(image_paths: List[str], read_attributes: bool = True,
                    max_frames: int = None) -> dict:
    """
    Consolidate a capture session into one user profile. Returns:
      {decision, identity, timeline, appearance, frames}
    `read_attributes=False` skips the per-frame attribute extraction (identity + timeline
    only) — useful for a fast 'is this a consistent person?' gate before the heavy read.
    """
    import cv2
    if max_frames is None:
        # Each attribute frame runs the MediaPipe face-mesh + hair-segmenter passes, so this
        # is the main latency + memory knob. Appearance is aggregated across frames, so a
        # small handful of the owner's best frames is plenty; default 3 (was 8) to stay fast
        # and fit a small host. Override with KREY_ATTR_FRAMES.
        max_frames = int(os.environ.get("KREY_ATTR_FRAMES") or "3")
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

    # A small crop of the face Krey locked onto as the owner, returned so the user can
    # eyeball 'yes, that's me' while checking the read. It's their own uploaded photo,
    # returned transiently to their own session — not stored (derive-and-discard holds).
    owner_thumb = _owner_thumb(faces, picks or user_idx)

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
            # Diagnostic: appearance comes back empty when the face-parser finds no face in the
            # crop (e.g. a downscaled full-body shot). Log crop size + which slices were read so
            # a failed read is explainable from the host logs rather than guessed at.
            if rec is None:
                ch, cw = (crop.shape[0], crop.shape[1]) if getattr(crop, "size", 0) else (0, 0)
                log.warning("attr read EMPTY: face=%dx%d crop=%dx%d photo=%s (face-parser found no face)",
                            x1 - x0, y1 - y0, cw, ch, f["photo"])
            else:
                got = [a for a in _ATTR_MODE if (rec.get(a) or {}).get("value") is not None]
                log.info("attr read OK: face=%dx%d photo=%s slices=%s", x1 - x0, y1 - y0, f["photo"], got or "none")
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

    # Summary of the whole read so a partial/empty result is explainable from the logs:
    # which appearance slices got a value, and how many faces/frames fed them.
    filled = [a for a in _ATTR_MODE if (appearance.get(a) or {}).get("value") is not None]
    log.info("capture read: faces=%d owner_faces=%d picks=%d frames_read=%d appearance_filled=%s decision=%s",
             len(faces), len(user_idx), len(picks), sum(1 for s in frames if s.get("read")),
             filled or "none", decision)

    return {
        "decision": decision,
        "identity": ident,
        "timeline": timeline,
        "appearance": appearance,
        "frames": frames,
        "owner_thumb": owner_thumb,      # small base64 crop of the picked owner face (transient)
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
