"""
Deterministic verification of the slice-2 measurement contract — no ML, no photo,
no pose model needed. Exercises the pure core: scale anchor, circumference,
per-field confidence, computed shape, the declared body_type cross-check, landmark
coverage, and the backend accuracy ledger.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
from app import measure_core as core
from app.body_models import assemble_body_models


def test_scale_uses_declared_height_anchor():
    # 1700 px tall person declared as 170 cm -> 10 px per cm.
    assert core.scale_from_pixel_height(1700, 170) == 10.0
    # Guard rails: no scale without a real pixel height or a real declared height.
    assert core.scale_from_pixel_height(0, 170) is None
    assert core.scale_from_pixel_height(1700, 0) is None


def test_circle_circumference_matches_pi_d():
    # When width == depth the ellipse is a circle: circumference == pi * D.
    c = core.ellipse_circumference(10.0, 10.0)
    assert abs(c - math.pi * 10.0) < 1e-6
    # Degenerate axis -> zero, never a crash.
    assert core.ellipse_circumference(0, 10) == 0.0


def test_depth_estimate_is_sex_and_part_specific():
    # Female waist ratio is 0.78 (salvaged population ratio).
    assert core.estimate_depth_cm("waist", 25.0, sex=2) == 25.0 * 0.78
    # Unknown part falls back to the 0.85 default rather than raising.
    assert core.estimate_depth_cm("unknown", 10.0, sex=1) == 10.0 * 0.85


def test_part_confidence_is_monotonic_and_penalises_estimate():
    high = core.part_confidence(0.9, 1.0, depth_measured=True, plausibility=1.0)
    low_vis = core.part_confidence(0.5, 1.0, depth_measured=True, plausibility=1.0)
    est = core.part_confidence(0.9, 1.0, depth_measured=False, plausibility=1.0)
    assert high > low_vis                    # better landmark visibility -> higher
    assert high > est                        # a real side-depth beats an estimate
    assert 0.05 <= low_vis <= 0.99           # always clamped into range


def test_plausibility_damps_absurd_readings_only():
    assert core.plausibility_factor("waist", 70.0) == 1.0      # normal -> full
    assert core.plausibility_factor("waist", 500.0) < 0.5      # absurd -> damped
    assert core.plausibility_factor("waist", 500.0) >= 0.1     # never zero


def test_computed_hourglass_shape():
    m = {
        "chest": {"circumference_cm": 90.0},
        "waist": {"circumference_cm": 65.0},
        "hip": {"circumference_cm": 90.0},
        "shoulder": {"width_cm": 38.0},
    }
    out = core.classify_body_shape(m, sex=2)
    assert out["shape"] == "Hourglass"
    assert out["family"] == "hourglass"


def test_body_type_crosscheck_agrees_disagrees_and_abstains():
    pear = {"shape": "Pear / Triangle", "family": "triangle"}
    assert core.crosscheck_body_type("pear", pear)["agreement"] is True
    assert core.crosscheck_body_type("apple", pear)["agreement"] is False
    # No declared value -> abstain (None), never a forced match.
    assert core.crosscheck_body_type(None, pear)["agreement"] is None


def test_landmark_coverage_counts_seventeen():
    full = {n: 0.9 for n in core.COCO_17}
    cov = core.landmark_coverage(full)
    assert cov["detected"] == 17 and cov["coverage"] == 1.0 and cov["missing"] == []
    partial = {"nose": 0.9, "left_eye": 0.9}     # only 2 of 17 clearly visible
    assert core.landmark_coverage(partial)["coverage"] == round(2 / 17, 3)


def test_ledger_is_backend_only_and_clean_when_confident():
    m = {p: {"confidence": 0.8} for p in ("chest", "waist", "hip")}
    cov = core.landmark_coverage({n: 0.9 for n in core.COCO_17})
    check = {"agreement": None}
    led = core.build_accuracy_ledger(m, cov, check, detect_confidence=0.9)
    assert led["surfaced_to_user"] is False          # spec §6 invariant
    assert led["body_confidence"] == 0.8
    assert led["flags"] == []


def test_ledger_flags_low_confidence_and_mismatch():
    m = {"waist": {"confidence": 0.3}}
    cov = core.landmark_coverage({n: 0.9 for n in list(core.COCO_17)[:8]})  # 8/17
    check = {"agreement": False}
    led = core.build_accuracy_ledger(m, cov, check, detect_confidence=0.4)
    assert "incomplete_landmarks" in led["flags"]
    assert "low_confidence_fields" in led["flags"]
    assert "body_type_mismatch" in led["flags"]
    assert "needs_recapture" in led["flags"]
    assert led["body_confidence"] < 0.6


def test_body_models_composes_skin_and_measurement_slices():
    skin = {"value": 6, "model": "deterministic-lab-mst-v0"}
    meas = {"waist": {"circumference_cm": 70.1, "confidence": 0.7}}
    rec = assemble_body_models(skin_tone=skin, measurements=meas)
    assert rec["skin_tone"]["value"] == 6
    assert rec["measurements"]["waist"]["confidence"] == 0.7
    assert rec["body_shape"] is None                 # slice not supplied -> unset
    assert rec["schema_version"] == core.SCHEMA_VERSION


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
