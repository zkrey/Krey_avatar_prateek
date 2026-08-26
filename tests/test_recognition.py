"""
Deterministic verification of the §6 overall avatar-confidence (recognition) score.
Backend-only 'is this recognisably them' — twin likeness, never product fit.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.recognition import avatar_confidence, recognition_from_body_models, load_config
from app.body_models import assemble_body_models, empty_body_models

ALL = {"skin_tone": 0.8, "hair_colour": 0.8, "landmark_coverage": 0.8,
       "eye_colour": 0.8, "hair_texture": 0.8}


def test_full_coverage_weighted_score():
    out = avatar_confidence(ALL)
    assert out["overall"] == 0.8 and out["weight_coverage"] == 1.0
    assert out["attributes_missing"] == [] and out["needs_recapture"] is False
    assert out["surfaced_to_user"] is False


def test_partial_coverage_renormalises_and_reports_gap():
    # Our current state: only skin + landmarks are built.
    out = avatar_confidence({"skin_tone": 0.8, "landmark_coverage": 0.8})
    assert out["overall"] == 0.8                      # renormalised over what's present
    assert out["weight_coverage"] == 0.55             # ...but only 55% of the §6 signal
    assert set(out["attributes_missing"]) == {"hair_colour", "eye_colour", "hair_texture"}


def test_low_score_flags_recapture():
    out = avatar_confidence({k: 0.4 for k in ALL})
    assert out["overall"] == 0.4 and out["needs_recapture"] is True   # below 0.60 floor


def test_single_attribute_coverage():
    out = avatar_confidence({"skin_tone": 0.5})
    assert out["overall"] == 0.5 and out["weight_coverage"] == 0.3


def test_no_attributes_is_zero_and_needs_recapture():
    out = avatar_confidence({})
    assert out["overall"] == 0.0 and out["weight_coverage"] == 0.0
    assert out["attributes_used"] == [] and out["needs_recapture"] is True


def test_weights_are_versioned_and_provisional():
    assert "provisional" in load_config()["version"]


def test_recognition_from_a_body_models_record():
    record = assemble_body_models(
        skin_tone={"value": 6, "confidence": 0.87},
        accuracy_ledger={"landmark_coverage": 1.0, "surfaced_to_user": False},
    )
    out = recognition_from_body_models(record)
    assert out["attributes_used"] == ["landmark_coverage", "skin_tone"]
    assert out["overall"] == 0.929 and out["weight_coverage"] == 0.55   # (0.87*.30 + 1.0*.25)/.55


def test_body_models_record_carries_avatar_confidence_slot():
    assert empty_body_models()["avatar_confidence"] is None
    rec = assemble_body_models(avatar_confidence={"overall": 0.9})
    assert rec["avatar_confidence"] == {"overall": 0.9}


def test_hair_and_eye_slices_lift_coverage_to_ninety_percent():
    # skin + landmarks alone = 55% of the §6 signal; adding hair_colour + eye_colour
    # takes it to 90% (only hair_texture, the unbuilt classifier, remains).
    record = assemble_body_models(
        skin_tone={"confidence": 0.8},
        hair_colour={"confidence": 0.8},
        eye_colour={"confidence": 0.8},
        hair_texture={"available": False, "confidence": None},   # stub omits itself
        accuracy_ledger={"landmark_coverage": 0.8},
    )
    out = recognition_from_body_models(record)
    assert out["weight_coverage"] == 0.9 and out["overall"] == 0.8
    assert out["attributes_missing"] == ["hair_texture"]


def test_texture_available_closes_coverage_to_full():
    record = assemble_body_models(
        skin_tone={"confidence": 0.8}, hair_colour={"confidence": 0.8},
        eye_colour={"confidence": 0.8}, accuracy_ledger={"landmark_coverage": 0.8},
        hair_texture={"available": True, "confidence": 0.8},   # now measured
    )
    out = recognition_from_body_models(record)
    assert out["weight_coverage"] == 1.0 and out["attributes_missing"] == []


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
