"""
Face-identity helpers shared by the capture sessions — the InsightFace/ArcFace accessor,
building a reference embedding for the user (the dominant identity in their own photos),
and matching a face to that reference.

Lazy/model-backed (InsightFace buffalo_l — research/non-commercial, see docs/scope_bakeins.md);
the clustering it leans on lives in the pure, tested `capture_core`.
"""
from __future__ import annotations
from typing import List, Optional, Sequence
from app import capture_core as cc

_app = None


def get_face_app(det_size: int = 1024):
    global _app
    if _app is None:
        from insightface.app import FaceAnalysis
        a = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        a.prepare(ctx_id=-1, det_size=(det_size, det_size))
        _app = a
    return _app


def detect_faces(img_bgr) -> List[dict]:
    """[{embedding, bbox=(x0,y0,x1,y1), age, det_score}] for every face in the frame."""
    out = []
    for f in get_face_app().get(img_bgr):
        x0, y0, x1, y1 = [int(v) for v in f.bbox]
        out.append({"embedding": [float(v) for v in f.normed_embedding],
                    "bbox": (x0, y0, x1, y1), "age": int(f.age),
                    "det_score": float(f.det_score)})
    return out


def reference_embedding(image_paths: Sequence[str]) -> Optional[list]:
    """Mean embedding of the dominant identity across the user's own photos (their twin anchor)."""
    import cv2
    import numpy as np
    faces, dates = [], []
    for p in sorted(image_paths):
        img = cv2.imread(p)
        if img is None:
            continue
        for f in detect_faces(img):
            faces.append(f["embedding"]); dates.append(None)
    if not faces:
        return None
    labels = cc.cluster_by_similarity(faces)
    user_c = cc.select_user_cluster(labels, dates)
    members = cc.members_by_cluster(labels)[user_c]
    ref = np.mean([faces[i] for i in members], axis=0)
    ref = ref / (np.linalg.norm(ref) + 1e-9)
    return [float(v) for v in ref]


def match(embedding: Sequence[float], reference: Sequence[float]) -> float:
    """Cosine similarity to a reference embedding (both L2-normalised)."""
    return cc._cosine(embedding, reference)


def find_user_face(img_bgr, reference: Sequence[float], threshold: float = cc.SAME_FACE_COSINE):
    """The face in this frame that best matches the reference, if any clears the threshold."""
    best, best_sim = None, threshold
    for f in detect_faces(img_bgr):
        sim = match(f["embedding"], reference)
        if sim >= best_sim:
            best, best_sim = f, sim
    return best
