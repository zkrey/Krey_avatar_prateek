"""
Deterministic verification of the fit-score rule engine (spec §5). No render, no GPU.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.fit_score import score_size, recommend_size, from_body_models, load_rules, METHOD

BODY = {"chest": 90.0, "waist": 76.0, "hip": 96.0}


def test_rules_load_from_config_and_method_tag():
    r = load_rules()
    assert "cut_ease_cm" in r and "UNCALIBRATED" in r["version"]
    out = score_size(BODY, {"chest": 98.0, "waist": 84.0, "hip": 104.0})
    assert out["method"] == METHOD == "rule-fit-v0"


def test_ideal_ease_is_a_clean_fit():
    # regular cut ideal ease = 8 cm on every girth -> fits.
    out = score_size(BODY, {"chest": 98.0, "waist": 84.0, "hip": 104.0})
    assert out["verdict"] == "fits"
    assert all(x["status"] == "fits" for x in out["regions"])


def test_tight_waist_sizes_up_but_borderline_is_only_snug():
    body = {"chest": 90.0, "waist": 90.0, "hip": 96.0}
    # waist girth == body girth -> 4 cm short of the min ease -> size_up (guardrail: not 'fits')
    up = score_size(body, {"chest": 98.0, "waist": 90.0, "hip": 104.0})
    assert up["verdict"] == "size_up" and up["binding_region"] == "waist"
    # 2 cm short -> within snug tolerance -> snug, never rounded to fits
    snug = score_size(body, {"chest": 98.0, "waist": 92.0, "hip": 104.0})
    assert snug["verdict"] == "snug"


def test_everything_roomy_sizes_down():
    out = score_size(BODY, {"chest": 110.0, "waist": 96.0, "hip": 116.0})
    assert out["verdict"] == "size_down"


def test_stretch_can_rescue_a_tight_garment():
    body = {"waist": 90.0}
    garment = {"waist": 90.0}
    assert score_size(body, garment, fabric_stretch="none")["verdict"] == "size_up"
    assert score_size(body, garment, fabric_stretch="high")["verdict"] == "fits"


def test_cut_changes_the_verdict():
    body, garment = {"chest": 90.0}, {"chest": 92.0}   # only 2 cm room
    assert score_size(body, garment, cut="slim")["verdict"] == "fits"     # slim wants little ease
    assert score_size(body, garment, cut="regular")["verdict"] == "snug"  # regular wants more


def test_recommend_size_picks_the_best_from_a_chart():
    chart = {
        "S": {"chest": 94.0, "waist": 80.0, "hip": 100.0},
        "M": {"chest": 100.0, "waist": 86.0, "hip": 106.0},
        "L": {"chest": 106.0, "waist": 92.0, "hip": 112.0},
    }
    out = recommend_size({"chest": 90.0, "waist": 78.0, "hip": 96.0},
                         {"cut": "regular", "fabric_stretch": "none", "size_chart": chart})
    assert out["best_size"] == "M" and out["verdict"] == "fits"


def test_confidence_is_higher_for_a_clear_fit_than_a_borderline_one():
    clear = score_size({"chest": 90.0}, {"chest": 98.0})     # room 8 = ideal, big margin
    edge = score_size({"chest": 90.0}, {"chest": 94.0})      # room 4 = right on the min edge
    assert clear["confidence"] > edge["confidence"]


def test_garment_source_is_carried_for_scan_and_b2b():
    out = score_size(BODY, {"chest": 98.0, "waist": 84.0, "hip": 104.0}, garment_source="scan")
    assert out["garment_source"] == "scan"


def test_from_body_models_reuses_slice2_measurements():
    # The real measured body from the body_1_front test image.
    measurements = {
        "chest": {"circumference_cm": 94.6, "confidence": 0.75},
        "waist": {"circumference_cm": 78.4, "confidence": 0.75},
        "hip":   {"circumference_cm": 98.0, "confidence": 0.75},
    }
    body_cm, conf = from_body_models(measurements)
    assert body_cm["waist"] == 78.4 and conf["waist"] == 0.75
    out = recommend_size(body_cm, {"cut": "regular", "fabric_stretch": "low",
                                   "size_chart": {"M": {"chest": 100.0, "waist": 86.0, "hip": 104.0}}},
                         confidence=conf)
    assert out["verdict"] in ("fits", "snug", "size_up", "size_down")
    assert out["confidence"] > 0.0


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
