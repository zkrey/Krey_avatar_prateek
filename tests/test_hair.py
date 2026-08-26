"""Deterministic verification of the hair-colour core (no ML, no photo)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.hair import classify_hair_colour, classify_hair_texture, HAIR_COLOURS, HAIR_TEXTURES


def test_each_hair_colour_classifies_to_itself():
    for name, rgb in HAIR_COLOURS.items():
        out = classify_hair_colour([rgb, rgb, rgb])
        assert out["value"] == name and out["confidence"] >= 0.95
        assert out["needs_confirm"] is False


def test_black_hair_reads_black():
    out = classify_hair_colour([(30, 25, 22), (26, 22, 20)])
    assert out["value"] == "black"


def test_spread_samples_flag_confirmation():
    out = classify_hair_colour([(28, 24, 22), (198, 168, 110)])   # black + blonde
    assert out["needs_confirm"] is True


def test_dyed_colour_is_flagged_as_coloured():
    out = classify_hair_colour([(200, 40, 200), (205, 45, 195)])  # magenta dye
    assert out["value"] == "coloured" and out["needs_confirm"] is True


def test_top_candidates_are_sorted_and_capped():
    out = classify_hair_colour([(96, 68, 46)])                    # ~medium brown
    labels = [c["label"] for c in out["top_candidates"]]
    deltas = [c["delta_e"] for c in out["top_candidates"]]
    assert labels[0] == "medium_brown" and len(labels) <= 5
    assert deltas == sorted(deltas)


def test_texture_is_unavailable_without_features():
    out = classify_hair_texture()
    assert out["available"] is False and out["value"] is None


def test_texture_classifier_bins_the_four_types():
    # (coherence high, curl low) = straight ... (coherence low, curl high) = coily
    cases = {
        "straight": {"coherence": 0.90, "curl_frequency": 0.05},
        "wavy":     {"coherence": 0.55, "curl_frequency": 0.25},
        "curly":    {"coherence": 0.30, "curl_frequency": 0.50},
        "coily":    {"coherence": 0.15, "curl_frequency": 0.90},
    }
    for expected, feats in cases.items():
        out = classify_hair_texture(feats)
        assert out["available"] is True and out["value"] == expected
        assert out["value"] in HAIR_TEXTURES and out["top_candidates"][0]["label"] == expected


def test_empty_samples_raise():
    with pytest.raises(ValueError):
        classify_hair_colour([])


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
