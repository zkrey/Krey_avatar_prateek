"""
Entitlements — the subscription gate for the play loop (pure stdlib, deterministic).

Doctrine (founder's call): every plan gets the SAME product — the same try-on, the same
fit engine, the same play surfaces. Nobody is sold a crippled feature set. Free and paid
differ on only two levers:

  1. QUOTA   — how many renders per day.       (free is capped; paid lifts the cap)
  2. SPEED   — which GPU lane the render runs.  (free = standard; paid = priority/warm)

The free cap is placed on purpose: generous enough to reach the *wow inflection* (the user
has felt the magic across a few looks), then firm enough that the wall itself converts —
"you've seen what this does; go unlimited + instant." `upsell_signal` fires the nudge at
that exact moment, never before the wow (nagging a cold user kills the feeling).

This is the mechanism, not the pricing. Plan contents are DATA (`PLANS`) so the founder
tunes every number without touching logic; real billing (Razorpay) and ₹ prices live
elsewhere and are gated on explicit permission. This module only decides, given a plan and
how much a user has played today: may they render now, in which lane, and is it the moment
to offer more. It is read at the render gate alongside `eligibility.can_render` — the two
are complementary: eligibility says *may this person render at all* (account + DOB); this
says *may this plan render right now, and how fast*.
"""
from __future__ import annotations
from typing import Optional

UNLIMITED = None  # a plan with quota == UNLIMITED never hits the wall

# Plan catalogue — SAME features across all rows; they differ only on quota + lane.
# Numbers are placeholders for the founder to tune (data, not logic). `lane` maps to the
# GPU pool the render worker uses: "priority" = kept-warm (1-3s), "standard" = may cold-start.
PLANS: dict[str, dict] = {
    "free": {"label": "Free", "daily_render_quota": 5,       "lane": "standard"},
    "plus": {"label": "Plus", "daily_render_quota": 50,      "lane": "priority"},
    "pro":  {"label": "Pro",  "daily_render_quota": UNLIMITED, "lane": "priority"},
}
DEFAULT_PLAN = "free"

# The user has "felt the wow" only after they've actually played with a few looks. Below
# this, we never surface an upsell — let the magic land first. (Tunable.)
WOW_THRESHOLD = 3
# Fire the upsell when they're at or within this many renders of the wall (the inflection).
UPSELL_WITHIN = 1


def get_plan(plan_id: Optional[str]) -> dict:
    """Resolve a plan id to its entitlement row; unknown / missing -> free (never crash on
    a bad plan string — default to the most-restricted, safest tier)."""
    row = PLANS.get((plan_id or "").strip().lower())
    return {"plan": (plan_id or DEFAULT_PLAN).strip().lower() if row else DEFAULT_PLAN,
            **(row or PLANS[DEFAULT_PLAN])}


def is_unlimited(plan_id: Optional[str]) -> bool:
    return get_plan(plan_id)["daily_render_quota"] is UNLIMITED


def remaining(plan_id: Optional[str], used_today: int) -> Optional[int]:
    """Renders left today; None means unlimited. Never negative."""
    quota = get_plan(plan_id)["daily_render_quota"]
    if quota is UNLIMITED:
        return None
    return max(0, int(quota) - max(0, int(used_today)))


def render_lane(plan_id: Optional[str]) -> str:
    """The GPU lane this plan renders in: 'priority' (warm, fast) or 'standard'."""
    return get_plan(plan_id)["lane"]


def upsell_signal(plan_id: Optional[str], used_today: int) -> dict:
    """
    Should we offer the upgrade right now, and why? The heart of the conversion doctrine:
    only after the wow (used >= WOW_THRESHOLD) and only at the wall (remaining <= UPSELL_WITHIN).
    Unlimited plans never see it. Returns a structured nudge the client renders tastefully.
    """
    plan = get_plan(plan_id)
    if plan["daily_render_quota"] is UNLIMITED:
        return {"show": False, "reason": "unlimited_plan"}
    used = max(0, int(used_today))
    left = remaining(plan_id, used)
    if used < WOW_THRESHOLD:
        # Pre-wow: let the magic land, never nag. (But still tell the truth about `left`.)
        return {"show": False, "reason": "pre_wow", "renders_left": left}
    if left is not None and left <= UPSELL_WITHIN:
        moment = "at_wall" if left == 0 else "approaching_wall"
        return {"show": True, "reason": "wow_inflection", "moment": moment,
                "renders_left": left,
                "message": ("You're loving this — go unlimited and skip the wait."
                            if left == 0 else
                            "One free render left today — upgrade for unlimited + instant.")}
    return {"show": False, "reason": "mid_quota", "renders_left": left}


def authorize(plan_id: Optional[str], used_today: int) -> dict:
    """
    The play-loop gate: given a plan and how many renders the user has already spent today,
    decide whether this next render is allowed, in which GPU lane, how many are left, and
    whether now is the moment to offer more. Deterministic; no GPU, no clock, no I/O —
    `used_today` is supplied by the caller (the daily counter lives in the store/DB).
    """
    plan = get_plan(plan_id)
    left = remaining(plan_id, used_today)
    allowed = (left is None) or (left > 0)
    return {
        "plan": plan["plan"],
        "label": plan["label"],
        "allowed": allowed,
        "lane": plan["lane"],
        "unlimited": left is None,
        "daily_quota": plan["daily_render_quota"],
        "renders_left": left,
        "reason": "ok" if allowed else "daily_quota_reached",
        "upsell": upsell_signal(plan_id, used_today),
    }
