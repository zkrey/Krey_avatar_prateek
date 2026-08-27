"""Deterministic verification of the StyleProfile contract + its fit-engine consumption."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import style_profile as sp
from app.fit_score import recommend_for_style, recommend_size

BODY = {"chest": 90.0, "waist": 90.0, "hip": 96.0, "shoulder": 110.0}
CHART = {
    "cut": "regular", "fabric_stretch": "none",
    "size_chart": {
        "M": {"chest": 98.0, "waist": 94.0, "hip": 104.0, "shoulder": 116.0},
        "L": {"chest": 104.0, "waist": 100.0, "hip": 110.0, "shoulder": 122.0},
        "XL": {"chest": 110.0, "waist": 106.0, "hip": 116.0, "shoulder": 128.0},
    },
}


# ---- profile assembly + normalisation --------------------------------------------------
def test_assemble_normalises_friendly_words():
    p = sp.assemble_style_profile(fit_feel="roomy",
                                  region_preferences={"waist": "skim", "shoulder": "snug"})
    assert p["fit_feel"] == "relaxed"                 # roomy -> relaxed
    assert p["region_preferences"] == {"waist": "relaxed", "shoulder": "fitted"}


def test_assemble_drops_unknown_levels_and_bad_offsets():
    p = sp.assemble_style_profile(region_preferences={"waist": "banana"},
                                  comfort_offset={"top": "L"})
    assert p["region_preferences"] == {} and p["comfort_offset"] == {}


def test_resolve_falls_back_to_fit_feel():
    p = sp.assemble_style_profile(fit_feel="relaxed")
    assert sp.resolve_region_preferences(p, ["chest", "waist"]) == {"chest": "relaxed", "waist": "relaxed"}


def test_sensitivity_nudges_region_roomier_but_explicit_pref_wins():
    p = sp.assemble_style_profile(fit_feel="true", sensitivities=["midsection"],
                                  region_preferences={"chest": "fitted"})
    res = sp.resolve_region_preferences(p, ["waist", "chest", "shoulder"])
    assert res["waist"] == "relaxed"      # nudged roomier by the midsection sensitivity
    assert res["chest"] == "fitted"       # explicit preference overrides the nudge
    assert res["shoulder"] == "true"      # untouched


def test_merge_prefers_update_and_unions_lists():
    base = sp.assemble_style_profile(fit_feel="true", sensitivities=["arms"])
    upd = sp.assemble_style_profile(fit_feel="relaxed", sensitivities=["midsection"],
                                    region_preferences={"waist": "relaxed"})
    m = sp.merge_style_profiles(base, upd)
    assert m["fit_feel"] == "relaxed"
    assert set(m["sensitivities"]) == {"arms", "midsection"}
    assert m["region_preferences"] == {"waist": "relaxed"}


# ---- the payoff: same body, profile changes the recommendation -------------------------
def test_style_profile_flatters_the_soft_region():
    # neutral 'true' preference vs a profile that wants the waist relaxed (soft midsection).
    plain = recommend_size(BODY, CHART, fit_preference="true")
    styled = recommend_for_style(BODY, CHART,
                                 sp.assemble_style_profile(sensitivities=["midsection"]))
    # the styled pick gives the waist more room -> at least as large a size, never tighter.
    order = ["M", "L", "XL"]
    assert order.index(styled["best_size"]) >= order.index(plain["best_size"])
    waist_region = next(r for r in styled["regions"] if r["area"] == "waist")
    assert waist_region["status"] in ("fits", "loose")     # not 'tight' on the sensitive area


def test_style_why_names_intent_without_insecurities():
    styled = recommend_for_style(BODY, CHART,
                                 sp.assemble_style_profile(sensitivities=["midsection"],
                                                           region_preferences={"shoulder": "true"}))
    why = styled["why"].lower()
    assert why and all(bad not in why for bad in ("fat", "belly", "insecure", "midsection"))


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
