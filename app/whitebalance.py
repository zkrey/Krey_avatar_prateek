"""
White-balance / illumination normalization — remove the lighting colour-cast before we
read skin, hair and eye colour, so the same person doesn't read a different shade under
warm vs cool light (the per-frame skin-tone swing the capture stress test exposed).

Pure numpy so the maths is unit-testable with a synthetic cast, no photo needed. Two
classic estimators, plus a face-appropriate one:

  - grey_world:   assume the scene average is neutral. Simple, but a face crop is
                  skin-dominated, so it fights the skin's real warmth — use with care.
  - white_patch:  assume the brightest pixels are white (a percentile, for robustness to
                  a single blown highlight). Keys off sclera / teeth / catchlights.
  - reference_gray: gains from an explicit set of KNOWN-neutral pixels (e.g. sclera) —
                  the most principled for faces when a neutral reference is available.

All return per-channel BGR gains; `apply_gains` rescales and clips. Gains are clamped so
a near-black or single-hue frame can't blow the image out.
"""
from __future__ import annotations
from typing import Optional, Sequence, Tuple
import numpy as np

BGR = Tuple[float, float, float]
_MAX_GAIN = 3.0
_MIN_GAIN = 0.33


def _normalise(gains: np.ndarray) -> np.ndarray:
    """Scale so the mean gain is 1 (preserve overall brightness) and clamp each channel."""
    gains = np.where(np.isfinite(gains) & (gains > 0), gains, 1.0)
    gains = gains / gains.mean()
    return np.clip(gains, _MIN_GAIN, _MAX_GAIN)


def grey_world_gains(img_bgr) -> np.ndarray:
    means = np.asarray(img_bgr, np.float32).reshape(-1, 3).mean(axis=0)
    return _normalise(means.mean() / np.maximum(means, 1e-6))


def white_patch_gains(img_bgr, percentile: float = 97.0) -> np.ndarray:
    px = np.asarray(img_bgr, np.float32).reshape(-1, 3)
    ref = np.percentile(px, percentile, axis=0)          # per-channel "white"
    return _normalise(ref.max() / np.maximum(ref, 1e-6))


def reference_gray_gains(neutral_pixels: Sequence[Sequence[float]]) -> np.ndarray:
    """Gains that drive a set of known-neutral BGR pixels to equal channels (grey)."""
    px = np.asarray(neutral_pixels, np.float32).reshape(-1, 3)
    if px.shape[0] == 0:
        return np.ones(3, np.float32)
    m = px.mean(axis=0)
    return _normalise(m.mean() / np.maximum(m, 1e-6))


def apply_gains(img_bgr, gains) -> np.ndarray:
    out = np.asarray(img_bgr, np.float32) * np.asarray(gains, np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


def white_balance(img_bgr, method: str = "white_patch", **kw):
    """Return (corrected_image, gains). method: grey_world | white_patch."""
    if method == "grey_world":
        gains = grey_world_gains(img_bgr)
    elif method == "white_patch":
        gains = white_patch_gains(img_bgr, kw.get("percentile", 97.0))
    else:
        raise ValueError(f"unknown white-balance method: {method}")
    return apply_gains(img_bgr, gains), gains
