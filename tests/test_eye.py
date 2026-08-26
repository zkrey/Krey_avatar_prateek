"""Deterministic verification of the eye-colour core (with the Indian dark-brown prior)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.eye import classify_eye_colour, EYE_COLOURS


def test_dark_brown_iris_reads_dark_brown_with_high_confidence():
    out = classify_eye_colour([(60, 40, 30), (58, 41, 31)])
    assert out["value"] == "dark_brown" and out["confidence"] >= 0.8
    assert out["prior_applied"] is True


def test_clearly_blue_iris_overrides_the_prior():
    out = classify_eye_colour([(108, 138, 168), (110, 140, 166)])
    assert out["value"] == "blue"                       # closeness beats the dark-brown prior


def test_prior_tips_an_ambiguous_reading_to_dark_brown():
    ambiguous = (84, 57, 40)                            # ~midway dark_brown/medium_brown
    with_prior = classify_eye_colour([ambiguous], apply_prior=True)
    assert with_prior["value"] == "dark_brown"          # the prior decides the toss-up


def test_top_candidates_present_and_probabilities_sorted():
    out = classify_eye_colour([(108, 138, 168)])
    probs = [c["prob"] for c in out["top_candidates"]]
    assert out["top_candidates"][0]["label"] == "blue"
    assert probs == sorted(probs, reverse=True) and len(probs) <= 5


def test_empty_samples_raise():
    with pytest.raises(ValueError):
        classify_eye_colour([])


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
