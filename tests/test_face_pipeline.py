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
    hair_samples_from_mask, iris_samples_from_landmarks, sample_hair_and_eyes,
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


def test_sample_hair_and_eyes_degrades_to_empties_without_models(monkeypatch):
    # no MODELS_DIR models present -> pipeline returns empties, never raises.
    monkeypatch.setenv("MODELS_DIR", "/nonexistent-models-dir")
    img = np.zeros((32, 32, 3), np.uint8)
    hair, iris, region = sample_hair_and_eyes(img)
    assert hair == [] and iris == [] and region is None


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
