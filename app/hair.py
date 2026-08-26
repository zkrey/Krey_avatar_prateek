"""
Hair attributes — Service A face slice (spec §4.2, §8).

COLOUR is deterministic and GPU-free — the same nearest-swatch-in-LAB approach as the
Monk skin core: clean hair-pixel samples -> median LAB -> nearest hair-colour category +
confidence + top candidates. TEXTURE (coily/curly/wavy/straight) is a visual-pattern
classification, not colour maths — it genuinely needs a small classifier / VLM (spec §8),
so it is an honest stub here (value None, available False) until that model exists.

The image pipeline that produces the samples (MediaPipe hair_segmenter -> hair mask ->
clean pixels) is lazy/model-backed and lives with the other pipelines; this module is the
deterministic, unit-testable core. Reuses the Monk LAB machinery (no duplication).
"""
from __future__ import annotations
from typing import Sequence, Tuple, Optional, Mapping
import json
import os
from app.monk import rgb_to_lab, delta_e76, _median_lab, _dispersion

RGB = Tuple[int, int, int]
_TEXTURE_CONFIG = os.path.join(os.path.dirname(__file__), "config", "texture.json")
_texture_rules: Optional[dict] = None


def load_texture_rules(path: Optional[str] = None) -> dict:
    global _texture_rules
    if path is not None:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if _texture_rules is None:
        with open(_TEXTURE_CONFIG, encoding="utf-8") as f:
            _texture_rules = json.load(f)
    return _texture_rules

# Representative natural hair colours (spec §4.2 categories).
HAIR_COLOURS: dict[str, RGB] = {
    "black":        (28, 24, 22),
    "dark_brown":   (58, 42, 32),
    "medium_brown": (96, 68, 46),
    "light_brown":  (140, 102, 66),
    "blonde":       (198, 168, 110),
    "red_auburn":   (122, 58, 38),
    "grey_silver":  (178, 176, 172),
}
HAIR_TEXTURES = ("coily", "curly", "wavy", "straight")

CONFIRM_THRESHOLD = 15.0     # LAB dispersion -> ask to confirm
CONFIDENCE_FLOOR = 0.65      # per-attribute floor (spec §6)
NATURAL_MAX_DELTA = 42.0     # beyond this from every natural swatch -> likely dyed/"coloured"

_SWATCH_LAB = {k: rgb_to_lab(v) for k, v in HAIR_COLOURS.items()}


def classify_hair_colour(samples: Sequence[RGB]) -> dict:
    """samples: clean hair-pixel RGBs. Returns a body_models-shaped hair_colour record."""
    if not samples:
        raise ValueError("no hair samples provided")
    labs = [rgb_to_lab(s) for s in samples]
    reading = _median_lab(labs)

    ranked = sorted(_SWATCH_LAB, key=lambda k: delta_e76(reading, _SWATCH_LAB[k]))
    nearest = ranked[0]
    delta = round(delta_e76(reading, _SWATCH_LAB[nearest]), 2)

    dispersion = _dispersion(labs)
    confidence = round(max(0.30, min(0.99, 1.0 - dispersion / 30.0)), 3)

    unnatural = delta > NATURAL_MAX_DELTA           # far from every natural colour -> dyed
    value = "coloured" if unnatural else nearest
    needs_confirm = unnatural or dispersion > CONFIRM_THRESHOLD or confidence < CONFIDENCE_FLOOR

    top = [{"label": k, "delta_e": round(delta_e76(reading, _SWATCH_LAB[k]), 2)}
           for k in ranked[:5]]
    return {
        "value": value,
        "confidence": confidence,
        "confirmed_by_user": False,
        "needs_confirm": needs_confirm,
        "delta_e": delta,
        "dispersion_lab": round(dispersion, 2),
        "top_candidates": top,
        "n_samples": len(samples),
        "model": "deterministic-lab-haircolour-v0",
    }


def classify_hair_texture(features: Optional[Mapping[str, float]] = None,
                          rules: Optional[dict] = None) -> dict:
    """
    Heuristic hair-texture classifier (spec §8 baseline; GPU-free).
    `features` = {coherence, curl_frequency} (both ~0..1) from the hair region — see
    `texture_features_from_region`. Combines them into a 0..1 texture_index and bins it
    into straight/wavy/curly/coily. With no features it stays an honest unavailable stub,
    so recognition treats texture as not-yet-measured.

    This is a modest v0 baseline; the spec's upgrade path is a small classifier / VLM.
    """
    if features is None:
        return {"value": None, "available": False, "candidates": list(HAIR_TEXTURES),
                "confidence": None, "needs_confirm": False, "model": "heuristic-texture-v0",
                "note": "no hair-region features supplied (needs the mask pipeline / a model)"}

    r = rules or load_texture_rules()
    wf, wc = r["weights"]["curl_frequency"], r["weights"]["coherence"]
    coh = max(0.0, min(1.0, float(features["coherence"])))
    freq = max(0.0, min(1.0, float(features["curl_frequency"])))
    index = (freq * wf + (1.0 - coh) * wc) / (wf + wc)          # 0 straight … 1 coily

    bins = r["bins"]
    if index <= bins["straight"]:
        value = "straight"
    elif index <= bins["wavy"]:
        value = "wavy"
    elif index <= bins["curly"]:
        value = "curly"
    else:
        value = "coily"

    centers = r["centers"]
    d = abs(index - centers[value])
    confidence = round(max(0.30, min(0.95, 0.95 - 1.5 * d)), 3)
    needs_confirm = confidence < r["confidence_floor"]
    top = [{"label": k, "distance": round(abs(index - centers[k]), 3)}
           for k in sorted(centers, key=lambda k: abs(index - centers[k]))]
    return {
        "value": value,
        "available": True,
        "confidence": confidence,
        "needs_confirm": needs_confirm,
        "top_candidates": top,
        "features": {"coherence": round(coh, 3), "curl_frequency": round(freq, 3),
                     "texture_index": round(index, 3)},
        "model": "heuristic-texture-v0",
    }


def texture_features_from_region(region_bgr, rules: Optional[dict] = None) -> dict:
    """
    Classical-CV features from a hair-region image (lazy; needs cv2/numpy). Strand-direction
    COHERENCE via the structure tensor (high=straight) and CURL_FREQUENCY via the fraction
    of high-frequency energy (high=coily). v0 heuristic — validate/calibrate on real hair.
    """
    import numpy as np
    import cv2
    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    jxx, jyy, jxy = float(np.mean(gx * gx)), float(np.mean(gy * gy)), float(np.mean(gx * gy))
    denom = jxx + jyy + 1e-6
    coherence = float(np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / denom)   # 0..1
    # high-frequency energy fraction as a curl proxy
    f = np.fft.fftshift(np.fft.fft2(gray - gray.mean()))
    mag = np.abs(f)
    h, w = mag.shape
    yy, xx = np.ogrid[:h, :w]
    rr = np.sqrt((yy - h / 2) ** 2 + (xx - w / 2) ** 2)
    high = float(mag[rr > 0.25 * min(h, w)].sum())
    curl_frequency = min(1.0, high / (mag.sum() + 1e-6))
    return {"coherence": min(1.0, coherence), "curl_frequency": curl_frequency}
