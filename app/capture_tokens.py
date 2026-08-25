"""
Capture-token hold — Service A, slice 3 (spec §6 "close the token leak").

Anti-spam for the CAPTURE grants (+20 first photo, +15 each after — Capture Pipeline
Spec §5). This is SEPARATE from the render-cost token-hold in `eligibility.py` (that one
reserves the price of a render and is left exactly as-is). Without this, a troll
uploading 5 junk/dog photos would earn the whole ladder.

Fix: a photo's grant accrues HELD and becomes CLAIMABLE only once that photo passes the
§6 cascade (`cascade.screen_input(...) -> passed=True`). A photo that fails FORFEITS its
grant. Only 'claimable' grants are real — 'held' and 'forfeited' count for nothing.

Resolving is driven solely by the cascade verdict — there is no independent
"is this photo good" judgement in this module. Pure stdlib, deterministic, no network.
"""
from __future__ import annotations
from dataclasses import dataclass

# The capture ladder (documented; the caller passes the amount to grant_capture_hold).
FIRST_PHOTO_GRANT = 20
SUBSEQUENT_PHOTO_GRANT = 15

_HELD = "held"
_CLAIMABLE = "claimable"
_FORFEITED = "forfeited"


@dataclass
class Hold:
    amount: int
    state: str  # "held" | "claimable" | "forfeited"


def grant_capture_hold(amount: int) -> Hold:
    """On upload: the grant accrues but is HELD — not yet claimable."""
    if amount < 0:
        raise ValueError("amount must be >= 0")
    return Hold(amount=amount, state=_HELD)


def resolve_capture_hold(hold: Hold, cascade_passed: bool) -> Hold:
    """
    Resolve a HELD grant against the cascade verdict for that photo:
    passed -> claimable; failed -> forfeited.
    Raises on a non-held (already-resolved) hold — no double-resolve.
    """
    if hold.state != _HELD:
        raise ValueError(f"cannot resolve a {hold.state!r} hold (already resolved)")
    return Hold(hold.amount, _CLAIMABLE if cascade_passed else _FORFEITED)


def claimable_total(holds: list) -> int:
    """Sum of only the 'claimable' grants. Held and forfeited grants count for nothing."""
    return sum(h.amount for h in holds if h.state == _CLAIMABLE)
