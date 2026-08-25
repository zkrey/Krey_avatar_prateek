"""
Deterministic verification of the capture-token hold (anti-spam) — slice 3 / spec §6.
Resolving is driven by the cascade verdict; garbage earns nothing. No network.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.capture_tokens import (
    Hold, grant_capture_hold, resolve_capture_hold, claimable_total,
    FIRST_PHOTO_GRANT, SUBSEQUENT_PHOTO_GRANT,
)
from app.cascade import InputSignals, screen_input

NO_FACE = InputSignals(subject_present=False, quality_confidence=0.0)
GOOD = InputSignals(subject_present=True, quality_confidence=0.9,
                    is_account_holder=True, same_person_across_set=True)


def test_grant_starts_held_and_is_not_yet_real():
    h = grant_capture_hold(FIRST_PHOTO_GRANT)
    assert h.state == "held" and h.amount == 20
    assert claimable_total([h]) == 0            # held never counts


def test_five_no_face_uploads_forfeit_all_and_earn_zero():
    # 5 junk photos: each fails the cascade -> every grant forfeited -> 0 claimable.
    holds = []
    for _ in range(5):
        h = grant_capture_hold(SUBSEQUENT_PHOTO_GRANT)
        passed = screen_input(NO_FACE)["passed"]        # cascade-driven, not judged here
        holds.append(resolve_capture_hold(h, passed))
    assert all(h.state == "forfeited" for h in holds)
    assert claimable_total(holds) == 0


def test_passing_photo_becomes_claimable_and_counts():
    h = grant_capture_hold(FIRST_PHOTO_GRANT)
    resolved = resolve_capture_hold(h, screen_input(GOOD)["passed"])
    assert resolved.state == "claimable" and resolved.amount == 20
    assert claimable_total([resolved]) == 20


def test_mix_three_pass_two_fail_counts_only_the_three():
    holds = []
    for verdict in (GOOD, GOOD, NO_FACE, GOOD, NO_FACE):
        h = grant_capture_hold(SUBSEQUENT_PHOTO_GRANT)
        holds.append(resolve_capture_hold(h, screen_input(verdict)["passed"]))
    assert sum(h.state == "claimable" for h in holds) == 3
    assert claimable_total(holds) == 3 * 15


def test_forfeited_and_held_never_add_to_claimable():
    held = grant_capture_hold(15)
    forfeited = resolve_capture_hold(grant_capture_hold(15), False)
    claimable = resolve_capture_hold(grant_capture_hold(20), True)
    assert claimable_total([held, forfeited, claimable]) == 20   # only the claimable one


def test_cannot_resolve_twice():
    h = resolve_capture_hold(grant_capture_hold(20), True)
    with pytest.raises(ValueError):
        resolve_capture_hold(h, True)          # already claimable, not held


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
