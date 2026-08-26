"""
Verification of the face image pipeline's PURE sampling cores with synthetic numpy
arrays — mask -> hair samples and iris landmarks -> iris samples. The MediaPipe model
shells are not exercised here (no model/GPU in the sandbox); they are thin wrappers that
delegate to these tested functions, and degrade to empties when a model is absent.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from app.face_pipeline import (
    hair_samples_from_mask, iris_samples_from_landmarks, sample_face,
    gate_from_face_count, iris_points, skin_samples_from_landmarks,
    LEFT_IRIS, RIGHT_IRIS,
)


def test_hair_samples_come_only_from_masked_pixels():
    # top half = brown hair (mask 1), bottom half = green background (mask 0).
    img = np.zeros((40, 40, 3), np.uint8)
    img[:20, :] = (32, 42, 58)      # BGR of a brown (RGB 58,42,32)
    img[20:, :] = (0, 200, 0)       # green background — must never be sampled
    mask = np.zeros((40, 40), np.float32)
    mask[:20, :] = 1.0

    samples, region = hair_samples_from_mask(img, mask)
    assert samples and region is not None
    # every sample is the brown hair colour, never the green background
    assert all(s == (58, 42, 32) for s in samples)
    assert region.shape[0] == 20            # crop is the hair band only


def test_hair_subsamples_and_drops_exposure_extremes():
    img = np.zeros((60, 60, 3), np.uint8)
    img[:, :] = (30, 40, 55)
    img[0:5, :] = (255, 255, 255)   # blown highlights -> dropped
    mask = np.ones((60, 60), np.float32)
    samples, _ = hair_samples_from_mask(img, mask, max_samples=100)
    assert len(samples) <= 100
    assert (255, 255, 255) not in samples


def test_black_hair_pixels_are_kept_not_dropped_as_underexposed():
    # The common Indian case: near-black hair (~RGB 22,24,28) must survive sampling.
    img = np.zeros((30, 30, 3), np.uint8)
    img[:, :] = (28, 24, 22)        # BGR -> RGB (22,24,28)
    samples, _ = hair_samples_from_mask(img, np.ones((30, 30), np.float32))
    assert samples and all(s == (22, 24, 28) for s in samples)


def test_hair_empty_mask_returns_nothing():
    img = np.zeros((20, 20, 3), np.uint8)
    samples, region = hair_samples_from_mask(img, np.zeros((20, 20), np.float32))
    assert samples == [] and region is None


def test_iris_samples_ring_around_centre():
    # a blue iris disc (RGB 30,60,150 -> BGR 150,60,30) with a black pupil centre.
    img = np.zeros((60, 60, 3), np.uint8)
    cx, cy, R = 30, 30, 10
    yy, xx = np.ogrid[:60, :60]
    d = np.hypot(xx - cx, yy - cy)
    img[d <= R] = (150, 60, 30)     # iris
    img[d <= 3] = (0, 0, 0)         # pupil (dark) -> excluded by the annulus + dark filter
    # landmarks: centre + 4 ring points at radius R
    pts = [(cx, cy), (cx - R, cy), (cx, cy - R), (cx + R, cy), (cx, cy + R)]
    samples = iris_samples_from_landmarks(img, pts)
    assert samples, "should sample the iris ring"
    assert all(s == (30, 60, 150) for s in samples)      # the blue iris, not the pupil


def test_iris_degenerate_geometry_is_empty():
    img = np.zeros((20, 20, 3), np.uint8)
    assert iris_samples_from_landmarks(img, [(5, 5)]) == []              # too few points
    assert iris_samples_from_landmarks(img, [(5, 5)] * 5) == []          # zero radius


def test_single_face_gate():
    assert gate_from_face_count(0) == "no_face"
    assert gate_from_face_count(1) == "ok"
    assert gate_from_face_count(2) == "multiple_faces"
    assert gate_from_face_count(5) == "multiple_faces"


def test_iris_points_pulls_the_two_eye_sets():
    lm = [(float(i), float(i)) for i in range(478)]     # full mesh incl. iris
    left, right = iris_points(lm)
    assert [lm[i] for i in LEFT_IRIS] == left
    assert [lm[i] for i in RIGHT_IRIS] == right


def test_iris_points_empty_when_no_iris_landmarks():
    lm = [(0.0, 0.0)] * 468                              # mesh without the iris head
    assert iris_points(lm) == ([], [])


def test_skin_samples_come_from_landmark_patches():
    from app.skin_tone import _FOREHEAD, _LEFT_CHEEK, _RIGHT_CHEEK
    img = np.full((200, 200, 3), (120, 150, 190), np.uint8)   # uniform skin (BGR)
    lm = [(100.0, 100.0)] * 478                                # all patches on skin
    samples = skin_samples_from_landmarks(img, lm)
    assert samples and all(s == (190, 150, 120) for s in samples)   # BGR -> RGB


def test_sample_face_no_model_is_no_face_and_never_raises(monkeypatch):
    # no MODELS_DIR models present -> gate no_face, all sample lists empty, no crash.
    monkeypatch.setenv("MODELS_DIR", "/nonexistent-models-dir")
    img = np.zeros((32, 32, 3), np.uint8)
    sig = sample_face(img)
    assert sig["gate"] == "no_face" and sig["n_faces"] == 0
    assert sig["skin_samples"] == [] and sig["hair_samples"] == []
    assert sig["iris_samples"] == [] and sig["hair_region"] is None


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
