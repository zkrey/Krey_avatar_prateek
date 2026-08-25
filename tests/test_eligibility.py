"""
Deterministic verification of the slice-3 eligibility chokepoint and token-hold.
No server, no network — pure policy logic. Age policy is jurisdiction-keyed (§10.2).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
import pytest
from app.eligibility import (
    age_on, is_minor, can_render, Eligibility, POLICY, M1_JURISDICTION,
    place_hold, commit_hold, release_hold, TokenHold, InsufficientTokens,
)

TODAY = date(2026, 8, 25)
ADULT = date(2000, 1, 1)     # 26
EXACT_18 = date(2008, 8, 25) # turns 18 today
ALMOST_18 = date(2008, 8, 26)# turns 18 tomorrow -> still 17
CHILD = date(2012, 1, 1)     # 14
IN = M1_JURISDICTION         # "IN"


def test_m1_jurisdiction_is_india():
    assert M1_JURISDICTION == "IN"
    assert POLICY["IN"] == {"adult_age": 18,
                            "minors_allowed_with_consent": False,
                            "cBehav_for_minors": False}


def test_age_and_minor_boundary():
    assert age_on(ADULT, TODAY) == 26
    assert age_on(EXACT_18, TODAY) == 18 and is_minor(EXACT_18, TODAY) is False
    assert age_on(ALMOST_18, TODAY) == 17 and is_minor(ALMOST_18, TODAY) is True


def test_unknown_jurisdiction_is_default_denied():
    e = can_render(True, True, ADULT, TODAY, 100, 10, "US", True)   # not in POLICY
    assert e.allowed is False and e.reason == "jurisdiction_not_supported"


def test_no_account_is_blocked():
    e = can_render(False, True, ADULT, TODAY, 100, 10, IN, True)
    assert e.allowed is False and e.reason == "no_account"


def test_unverified_dob_is_blocked():
    e = can_render(True, False, ADULT, TODAY, 100, 10, IN, True)
    assert e.allowed is False and e.reason == "dob_not_verified"


def test_india_adult_with_tokens_is_allowed():
    e = can_render(True, True, ADULT, TODAY, 100, 10, IN, True)
    assert e.allowed is True and e.reason == "ok"
    assert e.cBehav is True and e.is_minor is False


def test_india_minor_blocked_even_with_parental_consent():
    # §10.2: India blocks minors even WITH verifiable parental consent.
    e = can_render(True, True, CHILD, TODAY, 100, 10, IN, True, parental_consent_verified=True)
    assert e.allowed is False and e.reason == "minor_blocked_by_policy"
    assert e.cBehav is False and e.is_minor is True     # cBehav from policy row, not consent


def test_invalid_input_blocked_before_funds():
    # Paid-up adult, but the §6 cascade did not pass -> blocked BEFORE funds.
    e = can_render(True, True, ADULT, TODAY, 100, 10, IN, False)
    assert e.allowed is False and e.reason == "input_ineligible"


def test_adult_without_tokens_is_blocked():
    e = can_render(True, True, ADULT, TODAY, 5, 10, IN, True)
    assert e.allowed is False and e.reason == "insufficient_tokens"


def test_token_hold_place_commit_release():
    remaining, hold = place_hold(available=100, cost=30)
    assert remaining == 70 and hold.state == "held"
    assert commit_hold(hold).state == "committed"
    _, hold2 = place_hold(100, 30)
    restored, released = release_hold(remaining, hold2)
    assert restored == 100 and released.state == "released"


def test_token_hold_rejects_overdraw_and_double_spend():
    with pytest.raises(InsufficientTokens):
        place_hold(available=5, cost=10)
    _, hold = place_hold(100, 30)
    committed = commit_hold(hold)
    with pytest.raises(ValueError):
        commit_hold(committed)


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
