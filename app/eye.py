"""
Eye colour — Service A face slice (spec §4.4).

Deterministic and GPU-free: iris-pixel samples -> median LAB -> nearest eye-colour, but
with the spec's INDIAN DARK-BROWN PRIOR (0.75 on dark brown, 0.25 shared across the rest,
applied before the reading). Posterior = closeness(distance) x prior, argmax wins. Eye
colour tolerates a lower floor (0.55, spec §4.4) — it's a discrete category with few
error modes. Reuses the Monk LAB machinery.
"""
from __future__ import annotations
from typing import Sequence, Tuple
from app.monk import rgb_to_lab, delta_e76, _median_lab, _dispersion

RGB = Tuple[int, int, int]

EYE_COLOURS: dict[str, RGB] = {
    "dark_brown":   (60, 40, 30),
    "medium_brown": (108, 74, 50),
    "hazel":        (128, 104, 68),
    "green":        (104, 124, 86),
    "blue":         (108, 138, 168),
    "grey":         (140, 148, 150),
}
DARK_BROWN_PRIOR = 0.75      # Indian prior (spec §4.4)
CONFIDENCE_FLOOR = 0.55      # lower floor — discrete category
AMBIGUOUS_MARGIN = 0.10      # top-1 vs top-2 closer than this -> ask to confirm

_SWATCH_LAB = {k: rgb_to_lab(v) for k, v in EYE_COLOURS.items()}


def _priors() -> dict:
    others = (1.0 - DARK_BROWN_PRIOR) / (len(EYE_COLOURS) - 1)
    return {k: (DARK_BROWN_PRIOR if k == "dark_brown" else others) for k in EYE_COLOURS}


def classify_eye_colour(samples: Sequence[RGB], apply_prior: bool = True) -> dict:
    """samples: clean iris-pixel RGBs. Returns a body_models-shaped eye_colour record."""
    if not samples:
        raise ValueError("no iris samples provided")
    labs = [rgb_to_lab(s) for s in samples]
    reading = _median_lab(labs)

    prior = _priors() if apply_prior else {k: 1.0 for k in EYE_COLOURS}
    scores = {k: (1.0 / (1.0 + delta_e76(reading, _SWATCH_LAB[k]))) * prior[k]
              for k in EYE_COLOURS}
    total = sum(scores.values()) or 1.0
    probs = {k: scores[k] / total for k in scores}

    ranked = sorted(probs, key=probs.get, reverse=True)
    value = ranked[0]
    p1 = probs[value]
    p2 = probs[ranked[1]] if len(ranked) > 1 else 0.0

    dispersion = _dispersion(labs)
    disp_factor = max(0.3, 1.0 - dispersion / 40.0)
    confidence = round(max(0.05, min(0.99, p1 * disp_factor)), 3)
    needs_confirm = confidence < CONFIDENCE_FLOOR or (p1 - p2) < AMBIGUOUS_MARGIN

    top = [{"label": k, "prob": round(probs[k], 3)} for k in ranked[:5]]
    return {
        "value": value,
        "confidence": confidence,
        "confirmed_by_user": False,
        "needs_confirm": needs_confirm,
        "top_candidates": top,
        "dispersion_lab": round(dispersion, 2),
        "prior_applied": apply_prior,
        "n_samples": len(samples),
        "model": "deterministic-lab-eyecolour-v0",
    }
