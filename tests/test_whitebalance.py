"""
White-balance core verification with synthetic casts. This module is a tested, available
tool but is NOT wired into the default pipeline: measured on real face crops, per-frame
white balance did not reduce the skin-tone spread (naive methods made it worse; a
sclera-referenced version was within noise). Outlier-robust aggregation is what actually
helped — see app/capture_core.aggregate_numeric(robust=True).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from app import whitebalance as wb


def test_grey_world_removes_a_uniform_cast():
    # a neutral grey image tinted blue (BGR): grey-world should pull channels back level.
    img = np.zeros((16, 16, 3), np.uint8)
    img[:] = (200, 120, 120)                       # blue-heavy cast
    out, gains = wb.white_balance(img, method="grey_world")
    m = out.reshape(-1, 3).mean(axis=0)
    assert max(m) - min(m) < 12                    # channels roughly equalised


def test_white_patch_uses_brightest_as_white():
    img = np.full((16, 16, 3), (60, 60, 60), np.uint8)
    img[0:3, :] = (240, 180, 180)                  # bright blue-tinted "white" (>3% of pixels)
    out, gains = wb.white_balance(img, method="white_patch")
    assert gains[0] < gains[2]                      # blue channel scaled down vs red


def test_reference_gray_neutralises_known_pixels():
    neutral = [(220, 140, 130), (215, 138, 132)]   # sclera-like, blue-tinted
    gains = wb.reference_gray_gains(neutral)
    corrected = np.array(neutral, np.float32) * gains
    m = corrected.mean(axis=0)
    assert max(m) - min(m) < max(np.mean(neutral, axis=0)) * 0.10   # much closer to grey


def test_gains_are_clamped_and_mean_normalised():
    img = np.full((8, 8, 3), (5, 250, 5), np.uint8)   # extreme single-hue frame
    gains = wb.grey_world_gains(img)
    assert gains.min() >= wb._MIN_GAIN - 1e-6 and gains.max() <= wb._MAX_GAIN + 1e-6


def test_apply_gains_clips_to_byte_range():
    img = np.full((4, 4, 3), 200, np.uint8)
    out = wb.apply_gains(img, [2.0, 2.0, 2.0])
    assert out.max() <= 255 and out.dtype == np.uint8


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
