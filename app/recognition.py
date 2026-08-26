"""
Overall avatar confidence — the backend's recognition score (Capture Pipeline Spec §6).

Answers "is this recognisably them?" as one backend-only number combining per-attribute
confidences by weight. Never surfaced to the user; it drives the soft re-capture nudge
below the floor. Weights live in app/config/recognition.json (versioned, swappable).

Two honest properties:
- TWIN LIKENESS only — NOT product fit (a separate, stricter axis).
- Confidence is the model's certainty, not measured ground-truth recognition. The true
  self-recognition rate comes from the user confirm-step on real data, which recalibrates
  these weights. Below ~0.60 recognition is where users start saying "that's not me"
  (spec §1); the usable floor is ~0.76.

Partial coverage: hair/eye slices aren't built yet, so the score is computed over the
attributes ACTUALLY present, with the §6 weights renormalised, and `weight_coverage`
reports how much of the intended recognition signal was measured (so a high score over
low coverage isn't mistaken for the full picture). Pure stdlib, deterministic.
"""
from __future__ import annotations
from typing import Optional, Mapping
import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "recognition.json")
_cache: Optional[dict] = None

# Attribute names understood by the §6 formula.
ATTRIBUTES = ("skin_tone", "hair_colour", "landmark_coverage", "eye_colour", "hair_texture")


def load_config(path: Optional[str] = None) -> dict:
    global _cache
    if path is not None:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if _cache is None:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def avatar_confidence(attributes: Mapping[str, float], config: Optional[dict] = None) -> dict:
    """
    attributes: {name: 0..1} for the attributes ACTUALLY available (omit the rest).
    Returns the backend recognition record — never surfaced to the user.
    """
    cfg = config or load_config()
    weights = cfg["weights"]
    floor = cfg["recapture_floor"]

    present = {k: float(v) for k, v in attributes.items()
               if k in weights and v is not None}
    used_w = {k: weights[k] for k in present}
    wsum = sum(used_w.values())
    overall = round(sum(present[k] * used_w[k] for k in present) / wsum, 3) if wsum else 0.0
    overall = max(0.0, min(0.99, overall))

    return {
        "overall": overall,                         # weighted recognition score, 0..1
        "weight_coverage": round(wsum, 3),          # fraction of §6 signal actually measured
        "attributes_used": sorted(present),
        "attributes_missing": [k for k in weights if k not in present],
        "needs_recapture": overall < floor,         # spec §6: soft nudge below the floor
        "surfaced_to_user": False,                  # invariant: never shown
        "weights_version": cfg["version"],
    }


def recognition_from_body_models(record: Mapping, config: Optional[dict] = None) -> dict:
    """Pull the available attribute confidences out of a body_models record and score them."""
    attrs: dict[str, float] = {}
    skin = record.get("skin_tone")
    if skin and skin.get("confidence") is not None:
        attrs["skin_tone"] = skin["confidence"]
    hair = record.get("hair_colour")
    if hair and hair.get("confidence") is not None:
        attrs["hair_colour"] = hair["confidence"]
    eye = record.get("eye_colour")
    if eye and eye.get("confidence") is not None:
        attrs["eye_colour"] = eye["confidence"]
    texture = record.get("hair_texture")
    if texture and texture.get("available") and texture.get("confidence") is not None:
        attrs["hair_texture"] = texture["confidence"]   # stub omits itself until built
    ledger = record.get("accuracy_ledger")
    if ledger and ledger.get("landmark_coverage") is not None:
        attrs["landmark_coverage"] = ledger["landmark_coverage"]
    return avatar_confidence(attrs, config)
