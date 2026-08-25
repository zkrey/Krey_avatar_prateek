"""
Deterministic verification of the capture-token hold (anti-spam).
Garbage uploads must earn 0 claimable tokens; a valid photo's grant becomes claimable.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.capture_tokens import (
    grant_for_photo, accrue_capture_grant, settle_capture_grant, claimable_total,
    FIRST_PHOTO_GRANT, SUBSEQUENT_PHOTO_GRANT,
)
from app.cascade import InputSignals, screen_input


def test_grant_ladder():
    assert grant_for_photo(1) == FIRST_PHOTO_GRANT == 20
    assert grant_for_photo(2) == grant_for_photo(5) == SUBSEQUENT_PHOTO_GRANT == 15
    with pytest.raises(ValueError):
        grant_for_photo(0)


def test_five_garbage_uploads_earn_zero_claimable():
    # 5 no-face photos: each fails the cascade -> every grant voids -> 0 claimable.
    grants = []
    for i in range(1, 6):
        g = accrue_capture_grant(i)
        verdict = screen_input(InputSignals(subject_present=False, quality_confidence=0.0))
        grants.append(settle_capture_grant(g, verdict["passed"]))
    assert all(g.state == "void" for g in grants)
    assert claimable_total(grants) == 0


def test_passing_photo_grant_becomes_claimable():
    g = accrue_capture_grant(1)
    assert g.state == "held"
    verdict = screen_input(InputSignals(subject_present=True, quality_confidence=0.9,
                                        is_account_holder=True, same_person_across_set=True))
    settled = settle_capture_grant(g, verdict["passed"])
    assert settled.state == "claimable" and settled.amount == 20
    assert claimable_total([settled]) == 20


def test_mixed_set_counts_only_valid_photos():
    # Photo 1 valid (+20), photos 2-5 garbage (void) -> only 20 claimable.
    good = InputSignals(subject_present=True, quality_confidence=0.9,
                        is_account_holder=True, same_person_across_set=True)
    bad = InputSignals(subject_present=False, quality_confidence=0.0)
    grants = [
        settle_capture_grant(accrue_capture_grant(1), screen_input(good)["passed"]),
        *[settle_capture_grant(accrue_capture_grant(i), screen_input(bad)["passed"])
          for i in range(2, 6)],
    ]
    assert claimable_total(grants) == 20


def test_cannot_settle_twice():
    g = settle_capture_grant(accrue_capture_grant(1), True)
    with pytest.raises(ValueError):
        settle_capture_grant(g, True)   # already claimable, not held


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
