"""
StyleProfile — how a person WANTS to be dressed, distinct from how their body measures.

People wear what makes them feel confident, not what a tape says: a 34" waist may buy L
because the midsection feels soft. That gap (measured size vs worn size, and WHERE the
ease is wanted) is the most valuable fit signal we hold. This module is the pure,
deterministic contract for it — assembled from a warm intake conversation (see
app/style_intake.py) and consumed by the fit engine to recommend the user's BEST match,
not just the technically-correct size.

Guardrails (carried from the spec):
- `sensitivities` is private: it BIASES flattering drape, and is NEVER surfaced to the
  user. Derive-and-discard applies — keep this compact profile, discard the raw text.
- The twin body itself is never altered to flatter; confidence comes from size + drape +
  words around an honest body (a slimmed twin that then mis-fits is the worst outcome).
"""
from __future__ import annotations
from typing import Optional, Mapping, Sequence

# How a region should sit. Aliases map friendly intake words to the fit-engine ease levels.
FIT_LEVELS = ("fitted", "true", "relaxed", "oversized")
_ALIAS = {"skim": "relaxed", "skims": "relaxed", "loose": "relaxed", "roomy": "relaxed",
          "snug": "fitted", "tight": "fitted", "baggy": "oversized",
          "true_to_size": "true", "regular": "true"}
DEFAULT_FEEL = "true"
VERSION = "style-profile-v0"


def normalise_level(level: Optional[str]) -> Optional[str]:
    if level is None:
        return None
    lv = str(level).strip().lower().replace(" ", "_")
    lv = _ALIAS.get(lv, lv)
    return lv if lv in FIT_LEVELS else None


def empty_style_profile() -> dict:
    return {
        "version": VERSION,
        "fit_feel": DEFAULT_FEEL,            # overall default preference
        "region_preferences": {},            # area -> fit level (waist: relaxed, shoulder: true)
        "comfort_offset": {},                # category -> +/- sizes (top: +1) — worn vs measured
        "sensitivities": [],                 # PRIVATE: biases drape, never surfaced
        "confidence_notes": [],              # what makes them feel good (structured shoulders…)
        "source": "unset",                   # conversation | single_input | learned | unset
    }


def assemble_style_profile(
    fit_feel: Optional[str] = None,
    region_preferences: Optional[Mapping[str, str]] = None,
    comfort_offset: Optional[Mapping[str, int]] = None,
    sensitivities: Optional[Sequence[str]] = None,
    confidence_notes: Optional[Sequence[str]] = None,
    source: str = "conversation",
) -> dict:
    """Build a StyleProfile, normalising fit words to engine levels and dropping unknowns."""
    p = empty_style_profile()
    p["source"] = source
    feel = normalise_level(fit_feel)
    if feel:
        p["fit_feel"] = feel
    for area, level in (region_preferences or {}).items():
        lv = normalise_level(level)
        if lv:
            p["region_preferences"][area] = lv
    for cat, off in (comfort_offset or {}).items():
        try:
            p["comfort_offset"][cat] = int(off)
        except (TypeError, ValueError):
            continue
    p["sensitivities"] = [str(s) for s in (sensitivities or [])]
    p["confidence_notes"] = [str(s) for s in (confidence_notes or [])]
    return p


def resolve_region_preferences(profile: Optional[Mapping], areas: Sequence[str]) -> dict:
    """
    Per-area fit level for the fit engine: an explicit region preference wins, else the
    overall fit_feel. `sensitivities` nudges a region one step roomier when it maps to a
    body area (soft-midsection -> more waist/chest ease) — this is where 'flatter me'
    quietly enters the maths, without ever telling the user.
    """
    if not profile:
        return {a: DEFAULT_FEEL for a in areas}
    feel = profile.get("fit_feel", DEFAULT_FEEL)
    prefs = profile.get("region_preferences", {})
    sens_areas = _sensitivity_areas(profile.get("sensitivities", []))
    out = {}
    for a in areas:
        level = prefs.get(a, feel)
        if a in sens_areas and a not in prefs:      # explicit pref always wins over a nudge
            level = _roomier(level)
        out[a] = level
    return out


_SENSITIVITY_MAP = {
    "midsection": ("waist", "chest"), "belly": ("waist",), "tummy": ("waist",),
    "stomach": ("waist",), "waist": ("waist",), "chest": ("chest",),
    "arms": ("bicep", "forearm"), "thighs": ("thigh",), "hips": ("hip",),
}


def _sensitivity_areas(sensitivities: Sequence[str]) -> set:
    areas: set = set()
    for s in sensitivities:
        areas.update(_SENSITIVITY_MAP.get(str(s).strip().lower(), ()))
    return areas


def _roomier(level: str) -> str:
    i = FIT_LEVELS.index(level) if level in FIT_LEVELS else FIT_LEVELS.index(DEFAULT_FEEL)
    return FIT_LEVELS[min(i + 1, len(FIT_LEVELS) - 1)]


def merge_style_profiles(base: Optional[Mapping], update: Optional[Mapping]) -> dict:
    """
    Fold a new signal (a later conversation turn, or a learned nudge from feedback) onto a
    profile. Update wins per field; region prefs and offsets merge key-wise; lists union
    (order-preserving). Pure — the caller persists the result.
    """
    out = dict(empty_style_profile())
    for src in (base or {}, update or {}):
        for k in ("fit_feel", "source"):
            if src.get(k):
                out[k] = src[k]
        out["region_preferences"].update(src.get("region_preferences", {}))
        out["comfort_offset"].update(src.get("comfort_offset", {}))
        for k in ("sensitivities", "confidence_notes"):
            for v in src.get(k, []):
                if v not in out[k]:
                    out[k].append(v)
    return out
