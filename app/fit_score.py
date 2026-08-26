"""
Fit-score engine — the "does this garment fit you?" rule engine (spec §5).

The decouple that makes generative render cheap: "show me on me" is the render (GPU);
"does it fit" is answered HERE with NO render and NO GPU — measurements × garment
metadata (size chart, cut, fabric stretch) -> a verdict. Deterministic, pure stdlib
(rules in app/config/fit.json), so the whole contract is unit-testable.

Hard guardrail (spec §5): the render flatters; the fit-score tells the truth. A
borderline-tight region is reported `snug`, never rounded up to `fits`.

Stable output contract — a future 3D-mesh fit-truth engine (Path A, deferred to M2
premium/made-to-measure) can produce the SAME shape and slot in behind this interface:
    { method, verdict: "fits"|"snug"|"size_up"|"size_down",
      regions: [{area, status, room_cm, note}], binding_region, confidence, garment_source }
Callers depend on the contract, not on `method` (rule engine = "rule-fit-v0";
a mesh engine would be e.g. "mesh-fit-v1").
"""
from __future__ import annotations
from typing import Optional, Mapping
import json
import os

METHOD = "rule-fit-v0"
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "fit.json")
_cache: Optional[dict] = None


def load_rules(path: Optional[str] = None) -> dict:
    global _cache
    if path is not None:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if _cache is None:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def from_body_models(measurements_slice: Mapping) -> tuple[dict, dict]:
    """Extract body girths (cm) + per-field confidence from a slice-2 measurements record."""
    body_cm, conf = {}, {}
    for part, m in (measurements_slice or {}).items():
        if "circumference_cm" in m:
            body_cm[part] = float(m["circumference_cm"])
            if "confidence" in m:
                conf[part] = float(m["confidence"])
    return body_cm, conf


def score_size(
    body_cm: Mapping[str, float],
    garment_cm: Mapping[str, float],
    cut: str = "regular",
    fabric_stretch: str = "none",
    fit_preference: str = "true",
    confidence: Optional[Mapping[str, float]] = None,
    garment_source: Optional[str] = None,
    rules: Optional[dict] = None,
) -> dict:
    """
    Score one garment SIZE against a body. `garment_cm` is that size's girths (cm).
    `fit_preference` (fitted|true|relaxed|oversized) shifts the target ease — the same
    body may prefer a roomier size (measured M, wears L). It is per-garment, so outfit
    combinations (baggy top + baggy bottom) are just per-piece preferences.
    `garment_source` (catalog|wardrobe|scan) is echoed, never changes the maths.
    """
    r = rules or load_rules()
    base = r["cut_ease_cm"].get(cut, r["cut_ease_cm"]["regular"])
    pref = r.get("fit_preference_ease_cm", {}).get(fit_preference, 0)
    band = {"min": base["min"] + pref, "ideal": base["ideal"] + pref, "max": base["max"] + pref}
    give = r["stretch_give_cm"].get(fabric_stretch, 0)
    snug_tol = r["snug_tolerance_cm"]

    regions = []
    for area in sorted(set(body_cm) & set(garment_cm)):
        room = garment_cm[area] - body_cm[area] + give   # +ve = garment roomier than body
        if room < band["min"]:
            shortfall = band["min"] - room
            regions.append({"area": area, "status": "tight", "room_cm": round(room, 1),
                            "shortfall_cm": round(shortfall, 1),
                            "note": f"{shortfall:.1f} cm tight", "margin": shortfall})
        elif room > band["max"]:
            over = room - band["max"]
            regions.append({"area": area, "status": "loose", "room_cm": round(room, 1),
                            "note": f"{over:.1f} cm roomy", "margin": over})
        else:
            margin = min(room - band["min"], band["max"] - room)
            regions.append({"area": area, "status": "fits", "room_cm": round(room, 1),
                            "note": "comfortable", "margin": margin})

    tights = [x for x in regions if x["status"] == "tight"]
    looses = [x for x in regions if x["status"] == "loose"]

    if tights:  # tight is the binding truth — you can't wear what won't close
        binding = max(tights, key=lambda x: x["shortfall_cm"])
        verdict = "snug" if binding["shortfall_cm"] <= snug_tol else "size_up"
    elif looses and len(looses) == len(regions):
        binding = max(looses, key=lambda x: x["margin"])
        verdict = "size_down"
    else:
        # fits (possibly with some loose areas): binding = the tightest still-ok region
        fits = [x for x in regions if x["status"] == "fits"] or regions
        binding = min(fits, key=lambda x: x["margin"])
        verdict = "fits"

    clarity = min(0.99, 0.45 + binding["margin"] / 8.0)
    meas_conf = (confidence or {}).get(binding["area"], 0.8)
    conf = round(max(0.05, min(0.99, clarity * meas_conf)), 3)

    for x in regions:      # drop the internal sort key from the public record
        x.pop("margin", None)

    return {
        "method": METHOD,
        "verdict": verdict,
        "regions": regions,
        "binding_region": binding["area"],
        "confidence": conf,
        "fit_preference": fit_preference,
        "garment_source": garment_source,
    }


def recommend_size(
    body_cm: Mapping[str, float],
    garment: Mapping,
    fit_preference: str = "true",
    confidence: Optional[Mapping[str, float]] = None,
    rules: Optional[dict] = None,
) -> dict:
    """
    Pick the best size from a garment's size_chart for the user's fit_preference.
    `garment` = {cut, fabric_stretch, source?, size_chart: {SIZE: {area: girth_cm, ...}}}.
    Best = the size whose girths sit closest to (cut ideal ease + preference offset), so
    an 'oversized' preference recommends a bigger size than 'true'.
    """
    r = rules or load_rules()
    cut = garment.get("cut", "regular")
    stretch = garment.get("fabric_stretch", "none")
    source = garment.get("source")
    pref = r.get("fit_preference_ease_cm", {}).get(fit_preference, 0)
    target = r["cut_ease_cm"].get(cut, r["cut_ease_cm"]["regular"])["ideal"] + pref
    give = r["stretch_give_cm"].get(stretch, 0)

    best_size, best_cost = None, None
    for size, girths in garment["size_chart"].items():
        areas = set(body_cm) & set(girths)
        if not areas:
            continue
        cost = sum(abs((girths[a] - body_cm[a] + give) - target) for a in areas)
        if best_cost is None or cost < best_cost:
            best_size, best_cost = size, cost

    if best_size is None:
        return {"method": METHOD, "verdict": None, "regions": [], "binding_region": None,
                "confidence": 0.0, "fit_preference": fit_preference, "garment_source": source,
                "best_size": None, "note": "no comparable regions between body and chart"}

    scored = score_size(body_cm, garment["size_chart"][best_size], cut, stretch,
                        fit_preference, confidence, source, rules=r)
    scored["best_size"] = best_size
    return scored


def _sits_as(avg_room_cm: float, band: Mapping) -> str:
    """How a size looks on the body, independent of preference (describes the look)."""
    if avg_room_cm < band["min"]:
        return "tight"
    if avg_room_cm <= band["ideal"]:
        return "true to size"
    if avg_room_cm <= band["max"]:
        return "relaxed"
    return "oversized"


def grade_sizes(
    body_cm: Mapping[str, float],
    garment: Mapping,
    confidence: Optional[Mapping[str, float]] = None,
    rules: Optional[dict] = None,
) -> list:
    """
    Grade EVERY size in the chart for how it sits on this body — powers 'try a size
    up/down'. Returns per size: {size, sits_as, verdict, confidence, avg_room_cm}.
    `sits_as` (tight / true to size / relaxed / oversized) is preference-independent — it
    describes the look, so a user can pick the baggy or the fitted one on purpose. Outfit
    combinations are just grade_sizes run per garment.
    """
    r = rules or load_rules()
    cut = garment.get("cut", "regular")
    stretch = garment.get("fabric_stretch", "none")
    source = garment.get("source")
    band = r["cut_ease_cm"].get(cut, r["cut_ease_cm"]["regular"])
    give = r["stretch_give_cm"].get(stretch, 0)

    out = []
    for size, girths in garment["size_chart"].items():
        areas = sorted(set(body_cm) & set(girths))
        if not areas:
            continue
        rooms = [girths[a] - body_cm[a] + give for a in areas]
        avg_room = sum(rooms) / len(rooms)
        sc = score_size(body_cm, girths, cut, stretch, "true", confidence, source, rules=r)
        out.append({"size": size, "sits_as": _sits_as(avg_room, band),
                    "verdict": sc["verdict"], "confidence": sc["confidence"],
                    "avg_room_cm": round(avg_room, 1)})
    return out
