"""
Input eligibility cascade — Service A, slice 3 (spec §6): make the input earn the render.

Cheapest-first, so nothing reaches the GPU until cheap checks confirm it deserves the
spend (GPU is 94-98% of the bill). Ordering: Stage 0 (device, ~₹0) -> Stage 1 (server
CPU) -> [Stage 2 GPU, elsewhere]. The verdict here feeds the single `canRender`
chokepoint as `input_eligibility_passed`; it is never re-checked per feature.

Reuse, not rebuild (spec §6): "random/garbage" is just low confidence + failed
detections — the numbers slice 1 (skin `confidence` / `needs_confirm`) and slice 2
(measurement `detect_confidence` / ledger) already compute. This module consumes those
signals; it does NOT add a new quality detector. All thresholds live in
`app/config/cascade.json` so they can be calibrated on real data post-launch.

Fail path is gentle retake-coaching, never a hard wall — EXCEPT genuine safety blocks
(NSFW, not-the-account-holder). An underage face signal ROUTES TO REVIEW and never
produces an automated block (face age estimation is unreliable and legally fraught).

Pure stdlib + a JSON config: fully unit-testable without a photo or a model.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "cascade.json")
_cache: Optional[dict] = None


def load_thresholds(path: Optional[str] = None) -> dict:
    """Load (and cache) the cascade thresholds. Tests may pass an explicit path."""
    global _cache
    if path is not None:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if _cache is None:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


@dataclass
class InputSignals:
    """Normalized signals for one input, reused from the slice outputs + Stage-1 checks."""
    # Stage 0 (device, cheap) — from slice 1/2
    subject_present: bool                       # a face or a person was detected
    quality_confidence: float                   # reused confidence (skin / measurement)
    needs_confirm: bool = False                 # reused from monk (high dispersion) — soft
    # Stage 1 (server CPU) — from safety/identity detectors (consumed, not built here)
    nsfw: bool = False
    is_account_holder: Optional[bool] = None    # None = not yet checked
    same_person_across_set: Optional[bool] = None
    capture_relevance: Optional[float] = None   # 0..1: does it match the requested capture? (None = not checked)
    age_estimate_minor: bool = False            # ROUTES TO REVIEW, never an auto-block


def signals_from_slices(skin_result: Optional[dict] = None,
                        measure_result: Optional[dict] = None,
                        **stage1) -> InputSignals:
    """
    Build InputSignals from the actual slice-1 / slice-2 outputs — the reuse the spec
    asks for. Extra keyword args are Stage-1 signals (nsfw, is_account_holder, ...).
    """
    subject, conf, needs = False, 0.0, False
    if skin_result and skin_result.get("monk_tone"):
        subject = True
        mt = skin_result["monk_tone"]
        conf = max(conf, float(mt.get("confidence", 0.0)))
        needs = needs or bool(mt.get("needs_confirm", False))
    if measure_result and measure_result.get("status") == "ok":
        subject = True
        led = measure_result.get("accuracy_ledger", {})
        conf = max(conf, float(led.get("detect_confidence", led.get("body_confidence", 0.0))))
    return InputSignals(subject_present=subject, quality_confidence=conf,
                        needs_confirm=needs, **stage1)


def _result(passed: bool, stage: int, flags: list, action: str) -> dict:
    return {"passed": passed, "stage": stage, "quality_flags": flags, "action": action}


def screen_input(signals: InputSignals, thresholds: Optional[dict] = None) -> dict:
    """
    Run the cascade. Returns {passed, stage, quality_flags, action}.
    `action` is one of: "retake_coach" (gentle), "safety_block" (hard), "review",
    "proceed". Order is enforced: Stage 0 before Stage 1, and both before any render.
    """
    t = thresholds or load_thresholds()
    flags: list[str] = []

    # ---- STAGE 0 — on-device, ~₹0: no subject / too dark / too blurry / low-res ----
    if not signals.subject_present:
        return _result(False, 0, ["no_subject"], "retake_coach")
    if signals.quality_confidence < t["stage0"]["min_quality_confidence"]:
        return _result(False, 0, ["low_quality"], "retake_coach")

    # ---- STAGE 1 — server CPU: safety + identity + real quality gate ----
    if signals.nsfw:
        return _result(False, 1, ["nsfw"], "safety_block")          # genuine safety = hard block
    if signals.is_account_holder is False:
        return _result(False, 1, ["not_account_holder"], "safety_block")
    if signals.same_person_across_set is False:
        return _result(False, 1, ["identity_inconsistent"], "retake_coach")
    # Misleading / wrong-capture-type: a genuine photo that isn't the requested
    # capture (wrong pose, face where a full-body was asked). Real user -> gentle.
    if (signals.capture_relevance is not None
            and signals.capture_relevance < t["stage1"]["min_relevance_confidence"]):
        return _result(False, 1, ["wrong_capture_type"], "retake_coach")
    if signals.quality_confidence < t["stage1"]["min_quality_confidence"]:
        return _result(False, 1, ["quality_too_low"], "retake_coach")

    # Underage face signal: ROUTE TO REVIEW, never an automated block (spec §6).
    if signals.age_estimate_minor:
        flags.append("age_review")
        return _result(True, 1, flags, "review")   # valid input; age handled by DOB/review flow

    # Passed Stage 0 + Stage 1 -> eligible to reach the render gate.
    return _result(True, 1, flags, "proceed")
