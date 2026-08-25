"""Deterministic verification of the Monk classification core (no ML, no photo needed)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.monk import rgb_to_lab, classify, MONK_SWATCHES


def test_white_maps_to_reference_lab():
    L, a, b = rgb_to_lab((255, 255, 255))
    assert abs(L - 100) < 0.5 and abs(a) < 1 and abs(b) < 1


def test_each_swatch_classifies_to_itself():
    # Feeding a swatch's own colour must return that swatch, at high confidence.
    for idx, rgb in MONK_SWATCHES.items():
        out = classify([rgb, rgb, rgb])
        assert out["value"] == idx, f"MST{idx} misclassified as {out['value']}"
        assert out["confidence"] >= 0.95
        assert out["needs_confirm"] is False


def test_tight_samples_high_confidence():
    out = classify([(160, 126, 86), (159, 125, 87), (161, 127, 85)])  # ~MST6
    assert out["value"] == 6
    assert out["confidence"] >= 0.9
    assert out["needs_confirm"] is False


def test_spread_samples_flag_confirmation():
    # Samples straddling light MST5 and dark MST8 -> high dispersion -> needs_confirm.
    out = classify([(215, 189, 150), (96, 65, 52), (215, 189, 150), (96, 65, 52)])
    assert out["needs_confirm"] is True
    assert out["confidence"] < 0.6


def test_low_confidence_single_photo_trips_confirm():
    # Real-photo-derived patches (forehead lit, cheeks shadowed): a valid MST7 reading
    # whose confidence is below the 0.65 floor -> needs_confirm, even though dispersion
    # stays under CONFIRM_THRESHOLD. This is the single-photo case aggregation rescues.
    out = classify([(186, 128, 87), (106, 70, 48), (144, 88, 61)])
    assert out["value"] == 7
    assert out["confidence"] < 0.65
    assert out["needs_confirm"] is True


def test_near_swatch_snaps_to_nearest():
    # A colour just off MST7 should still land on 7.
    out = classify([(126, 89, 64)])
    assert out["value"] == 7


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
