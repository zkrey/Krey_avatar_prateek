"""
Capture-token hold — Service A, slice 3 (spec §6 "close the token leak").

DISTINCT from the render-cost hold in `eligibility.py` (that one reserves the price
of a render). This one is anti-spam for the CAPTURE grants: +20 for the first photo,
+15 for each of the others. Without this, a troll uploading 5 dog photos would earn
the full ladder. Fix (spec §6): a photo's grant accrues in a HELD / unclaimed state
and only becomes CLAIMABLE once that photo passes the §6 validity gate (the cascade).
A photo that fails the gate voids its grant — garbage earns nothing.

(This extends the existing "locked until account created" rule; account-creation is a
second, separate unlock handled upstream. Pure stdlib — unit-testable without a photo.)

Token amounts follow the capture ladder (Capture Pipeline Spec §5); reconcile with the
locked economy GRANT=100 at the token pass (sub-project spec §13).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

FIRST_PHOTO_GRANT = 20
SUBSEQUENT_PHOTO_GRANT = 15


def grant_for_photo(photo_index: int) -> int:
    """Ladder: +20 for the first photo (index 1), +15 for each subsequent one."""
    if photo_index < 1:
        raise ValueError("photo_index is 1-based")
    return FIRST_PHOTO_GRANT if photo_index == 1 else SUBSEQUENT_PHOTO_GRANT


@dataclass
class CaptureGrant:
    photo_index: int
    amount: int
    state: str  # "held" (accrued, unclaimed) | "claimable" (passed gate) | "void" (failed)


def accrue_capture_grant(photo_index: int) -> CaptureGrant:
    """On upload: the grant accrues but is HELD — not yet earned."""
    return CaptureGrant(photo_index, grant_for_photo(photo_index), "held")


def settle_capture_grant(grant: CaptureGrant, passed_validity_gate: bool) -> CaptureGrant:
    """
    Resolve a held grant against the cascade verdict for that photo:
    passed -> claimable; failed -> void (earns nothing).
    """
    if grant.state != "held":
        raise ValueError(f"cannot settle a {grant.state} grant")
    return CaptureGrant(grant.photo_index, grant.amount,
                        "claimable" if passed_validity_gate else "void")


def claimable_total(grants: Iterable[CaptureGrant]) -> int:
    """Sum of grants that passed the gate. Held and void grants count for nothing."""
    return sum(g.amount for g in grants if g.state == "claimable")
