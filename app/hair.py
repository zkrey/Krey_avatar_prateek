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
from typing import Sequence, Tuple
from app.monk import rgb_to_lab, delta_e76, _median_lab, _dispersion

RGB = Tuple[int, int, int]

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


def classify_hair_texture(_samples=None) -> dict:
    """
    Stub: hair texture needs a small classifier / VLM (spec §8) — it is NOT colour maths,
    so it cannot be done deterministically. Returns the contract with available=False so
    the recognition score honestly treats texture as not-yet-measured.
    """
    return {
        "value": None,
        "available": False,
        "candidates": list(HAIR_TEXTURES),
        "confidence": None,
        "needs_confirm": False,
        "model": "needs-classifier",
        "note": "texture classifier not built; hair_texture omitted from recognition until it is",
    }
