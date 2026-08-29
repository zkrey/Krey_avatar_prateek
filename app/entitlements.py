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

Which side of the wall any feature lands on is decided by The Habit Line (docs/DOCTRINE.md),
encoded here as `classify_feature` with the two-barrier model: FREE_HABIT (below both
barriers — confidence + ₹0 ops + the free daily render), PAID_METERED (Barrier 1: a produced
render beyond the daily one — token-metered per use), PAID_PROACTIVE (Barrier 2: Krey works
before you ask — unlocked by a token PASS, earned or bought, not metered per use; ₹999/yr is
the cash shortcut to that pass). The habit core can never be paid — a test pins that invariant.

Access to the paid side is spent in TOKENS, not a hard cash paywall — tokens are EARNED
(`earn_map`: in-app gamification + promotion/advocacy — referral, RAAQ, broadcast, PR,
WhatsApp owned-media) or bought, and reserved/committed at the render gate
(`eligibility.TokenHold`). `token_map` holds SAMPLE amounts only — the real numbers live in
the backend and finalise post-launch against measured GPU cost + the allowed free-tier
subsidy; every amount is env-overridable so ops retune without a code change.

This is the mechanism, not the pricing. The plan levers (`PLANS`: quota + lane) are best read
as how fast the wallet refills and which lane you render in; real billing (Razorpay) and ₹
prices live elsewhere and are gated on explicit permission. Read at the render gate alongside
`eligibility.can_render` — eligibility says *may this person render at all* (account + DOB);
this says *may this render happen now, at what token cost, and in which lane*.
"""
from __future__ import annotations
import os
from typing import Optional

# ── The Habit Line + the two barriers (docs/DOCTRINE.md) ──────────────────────────────
# Give away what removes forced cost and builds the habit; charge for the value created ON
# TOP of it. The wall is drawn in two places:
#   Barrier 1  Free -> Metered : at the CREATION line — a produced render beyond the free
#                                daily one. Reactive, real GPU. Token-metered.
#   Barrier 2  Metered -> Sub   : at the PROACTIVE line — Krey works before you ask (Style
#                                Me, planner). Subscription-native (KREY UNLIMITED).
# Everything answering "will this fit me?" and everything that costs ~₹0 stays BELOW both,
# free and unlimited — even when it converts (the no-moving-up rule, guarded by a test).
FREE_HABIT, PAID_METERED, PAID_PROACTIVE = "free_habit", "paid_metered", "paid_proactive"

# ── Token map — SAMPLE amounts, NOT final economic law ────────────────────────────────
# Placeholders to reason with. The real numbers live in the BACKEND and are finalised once
# the app ships, against measured per-render GPU cost + the free-tier subsidy we allow
# (Slice 4 benchmark). Centralised here + env-overridable (KREY_TOKEN_<KEY>) so ops retune
# the economy without a code change. Amounts in tokens; subscription in INR/year.
_TOKEN_DEFAULTS = {
    "GRANT": 100,                    # initial wallet on signup
    "DAILY_FREE_RENDERS": 5,         # free produced renders per day (the taste)
    "OWNCOST": 5,                    # Barrier 1 · render on your own garment (half — feeds wear-log)
    "COST": 10,                      # Barrier 1 · standard produced render (per-use)
    "LAZYCOST": 15,                  # Barrier 2 · one proactive multi-render (Style Me / planner)
    "UNLIMITED_PASS_TOKENS": 1200,   # Barrier 2 · a token PASS = unlimited+proactive for a period
    "KREY_UNLIMITED_INR_YR": 999,    # ...the cash shortcut to that same pass (unvalidated until Slice 4)
}


def token_map() -> dict:
    """Sample token amounts, overridable from the environment (KREY_TOKEN_<KEY>) so the
    backend can retune the economy without a code change. Final values settle post-launch
    against real GPU cost + allowed free-tier subsidy — these are NOT economic law."""
    m = dict(_TOKEN_DEFAULTS)
    for k in m:
        env = os.environ.get(f"KREY_TOKEN_{k}")
        if env is not None:
            try:
                m[k] = int(env)
            except ValueError:
                pass
    return m


# FREE — below both barriers: confidence ("will this fit me?"), ~₹0 ops, + the free daily
# render. Never metered. fit_answer MUST be a standalone action, never only bundled inside a
# render, or "will this fit me?" is paywalled behind COST (docs/DOCTRINE.md, Fix 1).
_HABIT_CORE = {
    "fit_answer":     "Standalone 'will this fit me?' — rule engine, ₹0, UNLIMITED (never only inside a render — Fix 1).",
    "model_preview":  "Garment on a stock model — cached, ₹0, confidence.",
    "angle_swipe":    "Turntable / angle-swipe — cached, ₹0, confidence.",
    "browse":         "Browse / discover — ₹0.",
    "compare":        "Compare looks side by side — ₹0 confidence.",
    "save":           "Save a look — ₹0; builds the data flywheel (Fix 2, free forever).",
    "skip":           "Skip a look — ₹0; taste signal (Fix 2, free forever).",
    "wear_log":       "Wear-log — ₹0; the asset we're acquiring (Fix 2, free forever).",
    "size_recommend": "Size recommendation — removes the forced cost of guessing.",
    "twin_build":     "The twin, built once and kept — the price of entry.",
    "daily_render":   "The first render each day — the free taste (DAILY_FREE_RENDERS).",
}
# PAID · Barrier 1 (Free -> Metered) — a PRODUCED render beyond the free daily one. Reactive
# creation, real GPU. Token-metered (or covered by earned tokens / the subscription).
_PAID_METERED = {
    "standard_render":     "A render beyond the free daily one (COST). Reactive creation.",
    "own_wardrobe_render": "Render on your own garment (OWNCOST, half — feeds the wear-log; tripwire: cut to free if it suppresses wardrobe-building, Fix 3).",
    "scan_a_fit":          "Render from a scanned garment (COST, not LAZYCOST — it's reactive; the scan itself is free, Fix 4).",
}
# PAID · Barrier 2 (Metered -> Pass) — PROACTIVE: Krey works before you ask. NOT metered
# per-use (proactive features fire many renders unpredictably — a flat pass caps GPU
# exposure for both sides). Still TOKEN-GOVERNED: a token PASS (UNLIMITED_PASS_TOKENS)
# unlocks unlimited+proactive for a period, earned OR bought; ₹999/yr is the cash shortcut
# to that same pass, not a separate cash-only door. The wall stays permeable.
_PAID_PROACTIVE = {
    "style_me":            "Krey styles you unprompted — proactive; behind the token pass.",
    "planner":             "A week / occasion plan — max proactive; behind the token pass.",
    "hyperreal_3d_render": "Photoreal 3D twin (Sohan's mesh+Blender, M2 premium) — new value on the 2D habit.",
    "hd_share_export":     "HD watermark-free share — new value on top (referral).",
    "wardrobe_planning":   "A managed closet — presupposes a formed habit.",
    "occasion_styling":    "Occasion / weather styling — proactive, additive.",
    "shop_the_look":       "Buy the look — new value layered on knowing the fit.",
}
_PAID = {**_PAID_METERED, **_PAID_PROACTIVE}
_TIER_OF = {**{k: FREE_HABIT for k in _HABIT_CORE},
            **{k: PAID_METERED for k in _PAID_METERED},
            **{k: PAID_PROACTIVE for k in _PAID_PROACTIVE}}
_BARRIER = {FREE_HABIT: 0, PAID_METERED: 1, PAID_PROACTIVE: 2}


def classify_feature(feature: str) -> dict:
    """The single call every feature passes through to land on a side of the wall. Returns
    the tier, which barrier it sits above (0 = free, 1 = metered, 2 = subscription), whether
    it's paid, and the reason. Unknown features default to FREE_HABIT — 'when in doubt, free'
    (docs/DOCTRINE.md): mis-charging for a habit-builder is the costly error, so the safe
    default protects the flywheel."""
    f = (feature or "").strip().lower()
    tier = _TIER_OF.get(f, FREE_HABIT)
    reason = (_HABIT_CORE.get(f) or _PAID.get(f)
              or "unclassified — defaults free (when in doubt, free; protect the habit)")
    return {"feature": f, "tier": tier, "barrier": _BARRIER[tier],
            "paid": tier != FREE_HABIT, "reason": reason}


# ── Earn — how a wallet fills without paying (SAMPLE grants, backend-tunable) ──────────
# Paid access is governed by tokens, and tokens are EARNED as well as bought, so the wall
# stays permeable. Two families:
#   in_app    — gamification within the product (usage, saving, capture, streaks).
#   promotion — advocacy / owned-media that GROWS Krey, on top of the in-app earns:
#               referral, RAAQ, broadcast, PR, WhatsApp owned-media app promotion.
# Grants are SAMPLE, centralised + env-overridable (KREY_EARN_<SOURCE>); final values and
# eligibility settle in the token pass. This captures the model, not the economy.
_EARN_DEFAULTS = {
    # in-app gamification
    "daily_use":       (5,   "in_app",    "Opening + using Krey today."),
    "save_look":       (1,   "in_app",    "Saving a look (the action is free; the token nudges the habit)."),
    "capture_photos":  (100, "in_app",    "Completing the capture set (existing capture grant)."),
    "streak":          (10,  "in_app",    "A usage streak."),
    # promotion / advocacy — the additional earn options, on top of in-app gamification
    "referral_friend": (50,  "promotion", "A referred friend who signs up + builds a twin."),
    "raaq":            (10,  "promotion", "Posting / answering a RAAQ (rate-a-fit) that drives engagement."),
    "broadcast":       (20,  "promotion", "Broadcasting a look to a channel / story."),
    "pr_feature":      (50,  "promotion", "A PR / press mention credited to the user."),
    "whatsapp_promo":  (20,  "promotion", "Sharing Krey via owned WhatsApp media (app promotion)."),
}


def earn_map() -> dict:
    """Sample earn grants, overridable from the environment (KREY_EARN_<SOURCE>). Amounts
    and eligibility finalise in the token pass; these capture the earn model, not the
    economy. Returns {source: {amount, family, note}}."""
    out = {}
    for src, (amt, family, note) in _EARN_DEFAULTS.items():
        env = os.environ.get(f"KREY_EARN_{src.upper()}")
        val = amt
        if env is not None:
            try:
                val = int(env)
            except ValueError:
                pass
        out[src] = {"amount": val, "family": family, "note": note}
    return out


def is_free_habit(feature: str) -> bool:
    """True when a feature is on the free side of the Habit Line. The habit core can never
    be paid — this is the invariant a test pins."""
    return not classify_feature(feature)["paid"]


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
