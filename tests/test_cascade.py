"""
Deterministic verification of the §6 input cascade and its wiring into the gate.
No photo, no model — pure signal logic over a JSON threshold config.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
from app.cascade import InputSignals, screen_input, signals_from_slices, load_thresholds
from app.eligibility import can_render, M1_JURISDICTION

GOOD = dict(subject_present=True, quality_confidence=0.9,
            is_account_holder=True, same_person_across_set=True)


def test_thresholds_load_and_are_flagged_uncalibrated():
    t = load_thresholds()
    assert "stage0" in t and "stage1" in t
    assert "UNCALIBRATED" in t["version"]   # placeholders, calibrate post-launch


def test_thresholds_come_from_config_not_literals():
    # Inject a stricter config: an input that passes under the default now fails,
    # proving the number is read from config rather than hardcoded.
    strict = {"stage0": {"min_quality_confidence": 0.95},
              "stage1": {"min_quality_confidence": 0.95, "min_relevance_confidence": 0.5}}
    sig = InputSignals(subject_present=True, quality_confidence=0.90,
                       is_account_holder=True, same_person_across_set=True)
    assert screen_input(sig)["passed"] is True                    # default thresholds
    assert screen_input(sig, thresholds=strict)["passed"] is False  # config drives it
    assert screen_input(sig, thresholds=strict)["stage"] == 0


def test_junk_no_face_rejected_at_stage0():
    out = screen_input(InputSignals(subject_present=False, quality_confidence=0.0))
    assert out["passed"] is False and out["stage"] == 0
    assert out["quality_flags"] == ["no_subject"] and out["action"] == "retake_coach"


def test_too_dark_low_quality_rejected_at_stage0():
    out = screen_input(InputSignals(subject_present=True, quality_confidence=0.10))
    assert out["passed"] is False and out["stage"] == 0
    assert out["quality_flags"] == ["low_quality"]


def test_valid_input_passes_both_stages():
    out = screen_input(InputSignals(**GOOD))
    assert out["passed"] is True and out["stage"] == 1 and out["action"] == "proceed"


def test_nsfw_is_a_hard_safety_block_at_stage1():
    out = screen_input(InputSignals(**{**GOOD, "nsfw": True}))
    assert out["passed"] is False and out["stage"] == 1
    assert out["quality_flags"] == ["nsfw"] and out["action"] == "safety_block"


def test_not_account_holder_is_blocked():
    out = screen_input(InputSignals(**{**GOOD, "is_account_holder": False}))
    assert out["passed"] is False and out["quality_flags"] == ["not_account_holder"]


def test_wrong_capture_type_is_gentle_retake():
    # A genuine photo of you, but not the requested capture (low relevance).
    out = screen_input(InputSignals(**{**GOOD, "capture_relevance": 0.2}))
    assert out["passed"] is False and out["stage"] == 1
    assert out["quality_flags"] == ["wrong_capture_type"] and out["action"] == "retake_coach"


def test_relevant_capture_passes_and_unset_relevance_is_skipped():
    assert screen_input(InputSignals(**{**GOOD, "capture_relevance": 0.9}))["passed"] is True
    assert screen_input(InputSignals(**GOOD))["passed"] is True   # None -> not checked


def test_underage_signal_routes_to_review_never_auto_blocks():
    out = screen_input(InputSignals(**{**GOOD, "age_estimate_minor": True}))
    assert out["passed"] is True                     # never an automated block (spec §6)
    assert "age_review" in out["quality_flags"] and out["action"] == "review"


def test_signals_reused_from_slice_outputs():
    skin = {"monk_tone": {"confidence": 0.9, "needs_confirm": False}}
    measure = {"status": "ok", "accuracy_ledger": {"detect_confidence": 0.8}}
    sig = signals_from_slices(skin_result=skin, measure_result=measure,
                              is_account_holder=True, same_person_across_set=True)
    assert sig.subject_present is True and sig.quality_confidence == 0.9
    assert screen_input(sig)["passed"] is True


def test_order_gpu_never_reached_before_stage0_and_1_pass():
    # A no-face photo fails the cascade; feeding that verdict into the gate blocks
    # BEFORE funds even for a paid-up adult -> GPU is never reached.
    verdict = screen_input(InputSignals(subject_present=False, quality_confidence=0.0))
    assert verdict["passed"] is False
    e = can_render(True, True, date(2000, 1, 1), date(2026, 8, 25),
                   token_balance=100, render_cost=10,
                   jurisdiction=M1_JURISDICTION, input_eligibility_passed=verdict["passed"])
    assert e.allowed is False and e.reason == "input_ineligible"


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
