"""
Render-benchmark scorer — does the generated try-on still look like the SAME person?

The M1 bet is ~85% *likeness* (recognisable, not a mirror). A generative try-on is only
worth building if it PRESERVES the person's identity while changing the garment. This scores
that with Krey's OWN ArcFace recognition (app.identity) — the same number the product uses to
decide "is this recognisably them" — so the benchmark judges the render on the real bar, not a
toy metric.

Usage (CPU or GPU; needs the CV stack — runs great on Colab):
    KREY_FACE_MODEL=buffalo_l python -m bench.render_eval --original person.jpg --render tryon.jpg

Prints the identity cosine similarity between the original person and the rendered try-on, plus
a PASS/FAIL against a floor. On Colab set KREY_FACE_MODEL=buffalo_l for the accurate model.
"""
from __future__ import annotations
import argparse

# ArcFace cosine for the SAME identity across images sits high; a faithful try-on should keep
# the face matching the original. This floor is a starting line — recalibrate once we have a
# batch of real renders scored against tester judgements (same discipline as the alpha flags).
RECOGNISABLE_COSINE = 0.50


def _best_face(img_bgr):
    """The most prominent face in a frame (highest det_score x area), or None."""
    from app.identity import detect_faces
    faces = detect_faces(img_bgr)
    if not faces:
        return None

    def score(f):
        x0, y0, x1, y1 = f["bbox"]
        return f["det_score"] * max(1, (x1 - x0) * (y1 - y0))
    return max(faces, key=score)


def identity_similarity(original_path: str, render_path: str) -> float:
    """Cosine similarity between the original person's face and the rendered try-on's face."""
    import cv2
    from app.identity import match
    a = cv2.imread(original_path)
    b = cv2.imread(render_path)
    if a is None or b is None:
        raise SystemExit("could not read one of the images")
    fa, fb = _best_face(a), _best_face(b)
    if fa is None:
        raise SystemExit("no face found in the ORIGINAL image")
    if fb is None:
        raise SystemExit("no face found in the RENDER — the try-on hid or garbled the face")
    return match(fa["embedding"], fb["embedding"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score identity preservation of a try-on render.")
    ap.add_argument("--original", required=True, help="the person's real photo")
    ap.add_argument("--render", required=True, help="the generated try-on image")
    ap.add_argument("--floor", type=float, default=RECOGNISABLE_COSINE)
    a = ap.parse_args(argv)
    sim = identity_similarity(a.original, a.render)
    ok = sim >= a.floor
    verdict = "PASS — recognisably the same person" if ok else "FAIL — identity drifted"
    print(f"identity cosine = {sim:.3f}  (floor {a.floor:.2f})  ->  {verdict}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
