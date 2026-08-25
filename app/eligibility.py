"""
Eligibility — Service A, slice 3: the single `canRender` chokepoint.

The invariants require ONE wall, never a per-feature check (that is how the guest
leak happened). Everything that would process biometrics or start a render asks
`can_render(...)` first. It is pure stdlib and deterministic, so the whole policy is
unit-testable without a server.

Rules enforced here (spec §10.2 + handoff invariants):
  1. No account + verified DOB -> no biometric / no render.        (invariant 1)
  2. Age policy is JURISDICTION-KEYED via POLICY[jurisdiction]. M1 populates only
     India ('IN'); every other jurisdiction default-denies. The India row BLOCKS
     minors even with verifiable parental consent — DPDP §9 would allow consent,
     but spec §10.2 forbids persisting minor captures, and the stricter rule wins.
  3. cBehav for minors is set by the policy row (False for India), never bought by
     consent — consent can never buy behavioural tracking.         (invariant 3)
  + A token-hold reserves the render's cost up front, so a render never starts
    unless it can be paid for (must exist before any GPU spend — build seq §14).

Real country-detection and any policy row beyond India are a post-launch,
counsel-gated workstream. This module only holds the shape; it does not decide the
law. `parental_consent_verified` stays as an upstream-verified boolean, used only
by jurisdictions whose policy allows consented minors (India's does not).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional

ADULT_AGE = 18  # default for the jurisdiction-agnostic is_minor() helper

# Jurisdiction-keyed age policy (spec §10.2). M1 populates India only; any
# jurisdiction absent from POLICY is default-denied by can_render.
POLICY: dict[str, dict] = {
    "IN": {"adult_age": 18, "minors_allowed_with_consent": False, "cBehav_for_minors": False},
}

# M1 ships India-only.
# TODO: replace with real upstream country-detection (billing / SIM / declared
# residence) — a legal question, needs counsel. Until then every gate call passes
# M1_JURISDICTION and non-IN users default-deny.
M1_JURISDICTION = "IN"


# ---------------------------------------------------------------------------
# Age
# ---------------------------------------------------------------------------
def age_on(birthdate: date, today: date) -> int:
    """Whole years from birthdate to today."""
    years = today.year - birthdate.year
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        years -= 1
    return years


def is_minor(birthdate: date, today: date) -> bool:
    return age_on(birthdate, today) < ADULT_AGE


# ---------------------------------------------------------------------------
# The chokepoint
# ---------------------------------------------------------------------------
@dataclass
class Eligibility:
    allowed: bool
    reason: str            # machine reason ("ok", "no_account", ...)
    cBehav: bool           # behavioural tracking allowed? (false for minors)
    is_minor: bool
    age: Optional[int]


def can_render(
    account_present: bool,
    dob_verified: bool,
    birthdate: Optional[date],
    today: date,
    token_balance: int,
    render_cost: int,
    jurisdiction: str,
    input_eligibility_passed: bool,
    parental_consent_verified: bool = False,
) -> Eligibility:
    """
    The one wall. Returns an Eligibility verdict; callers must respect `allowed`.
    Order: jurisdiction, identity, age policy, input eligibility, then funds.
    `input_eligibility_passed` is the §6 cascade verdict (Stage 0+1). Checking it
    before funds means a valid, paid-up account can never render an invalid/unsafe
    input (a dog photo, someone else's face) — and GPU is never reached first.
    """
    # 0) jurisdiction — unknown jurisdictions default-deny (spec §10.2).
    policy = POLICY.get(jurisdiction)
    if policy is None:
        return Eligibility(False, "jurisdiction_not_supported", False, False, None)

    # 1) identity — no biometric/render without an account and a verified DOB.
    if not account_present:
        return Eligibility(False, "no_account", False, False, None)
    if not dob_verified or birthdate is None:
        return Eligibility(False, "dob_not_verified", False, False, None)

    age = age_on(birthdate, today)
    minor = age < policy["adult_age"]
    # invariant 3: minors' cBehav comes from the policy row, never from consent.
    cbehav = policy["cBehav_for_minors"] if minor else True

    # 2) age policy — resolved from the jurisdiction's row.
    if minor:
        if not policy["minors_allowed_with_consent"]:
            # India: minors blocked even WITH consent (§10.2 no-persistence rule).
            return Eligibility(False, "minor_blocked_by_policy", cbehav, True, age)
        if not parental_consent_verified:
            return Eligibility(False, "minor_parental_consent_required", cbehav, True, age)

    # 3) input eligibility — the §6 cascade (Stage 0+1) must have passed first, so
    #    no invalid/unsafe input ever reaches funds or the GPU.
    if not input_eligibility_passed:
        return Eligibility(False, "input_ineligible", cbehav, minor, age)

    # 4) funds — must be able to pay for the render before it starts.
    if token_balance < render_cost:
        return Eligibility(False, "insufficient_tokens", cbehav, minor, age)

    return Eligibility(True, "ok", cbehav, minor, age)


# ---------------------------------------------------------------------------
# Token-hold: reserve the cost up front, then commit or release.
# ---------------------------------------------------------------------------
@dataclass
class TokenHold:
    amount: int
    state: str  # "held" | "committed" | "released"


class InsufficientTokens(Exception):
    pass


def place_hold(available: int, cost: int) -> tuple[int, TokenHold]:
    """Reserve `cost` tokens. Returns (remaining_available, hold)."""
    if cost < 0:
        raise ValueError("cost must be >= 0")
    if available < cost:
        raise InsufficientTokens(f"need {cost}, have {available}")
    return available - cost, TokenHold(amount=cost, state="held")


def commit_hold(hold: TokenHold) -> TokenHold:
    """Render succeeded — the reserved tokens are spent."""
    if hold.state != "held":
        raise ValueError(f"cannot commit a {hold.state} hold")
    return TokenHold(hold.amount, "committed")


def release_hold(available: int, hold: TokenHold) -> tuple[int, TokenHold]:
    """Render failed/cancelled — give the reserved tokens back."""
    if hold.state != "held":
        raise ValueError(f"cannot release a {hold.state} hold")
    return available + hold.amount, TokenHold(hold.amount, "released")
