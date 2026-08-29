# Krey monetization doctrine — The Habit Line

The single rule that decides which side of the paywall any feature lands on:

> **Give away the thing that removes forced cost and builds the habit.
> Charge for the thing that creates new value on top of the habit.**

This is the barrier between free and paid. Everything below serves it.

## Why

A user's habit is worth more to us than a user's first payment. The habit is *knowing how
clothes fit you* — checked casually, daily, without the old forced cost (buying to find out,
the anxiety of getting it wrong, the return). If we charge for that, we tax the very
behaviour we need to become universal, and the flywheel never spins. So we give the habit
away. We charge for the value that only *exists because the habit exists* — and a user who
already has the habit pays for that value gladly, because it's additive, not ransomed.

## The line, drawn

**FREE — the habit (never behind the wall):**
- The fit answer — *does this fit me, what size* (CPU, instant, ₹0).
- Try-on — seeing yourself in a garment.
- The twin — built once, kept.
- Browsing / the rail / size recommendations.

These build the habit and remove forced cost. They are the **same product for everyone** —
free is never a crippled core. A habit-builder is **never** moved behind the wall to juice
conversion; doing so breaks the habit and kills the flywheel. This is a hard invariant.

**PAID — value on top of the habit, drawn at two barriers:**

- **Barrier 1 · Free → Metered** — at the **creation line**. A *produced render beyond the
  free daily one*: `standard_render`, `own_wardrobe_render`, `scan_a_fit`. Reactive, real
  GPU, token-metered. Everything answering "will this fit me?" and everything ~₹0 stays
  *below* this line, free and unlimited.
- **Barrier 2 · Metered → Pass** — at the **proactive line**. Krey doing work the user
  didn't ask for: `style_me`, `planner`, and the M2 **premium** `hyperreal_3d_render`
  (Sohan's mesh + Blender, gated on the M1 fit-score reaching ~85% — docs/scope_bakeins.md),
  plus HD share, wardrobe, occasion styling, shop-the-look. **Not** metered per use
  (proactive features fire many renders unpredictably; a flat pass caps GPU exposure for
  both sides) — but **still token-governed**: a token **pass** (`UNLIMITED_PASS_TOKENS`)
  unlocks unlimited + proactive for a period, *earned or bought*; **₹999/yr is the cash
  shortcut to that same pass, not a separate cash-only door**. Nothing is looped out of the
  token economy — cash only ever buys tokens (or the pass), so a non-payer can still grind
  their way in and the wall stays permeable.

The 2D try-on builds the habit and stays free; hyperreal 3D is new value on top of it, never
a replacement. Each paid feature is admitted **only if it passes the three seams below**.

## The three seams (the classifier)

An item is filed correctly only when all three agree with its price:

| Seam | Free side | Paid side |
|---|---|---|
| **S1 · Confidence vs Creation** | "will this work on me?" | "make me the thing" |
| **S2 · Reactive vs Proactive** | they ask, you answer | you work before they ask |
| **S3 · Marginal cost to Krey** | ~₹0 to serve | real GPU-seconds |

Confidence is removed friction (never charge for it — the rent-seeking electrician);
creation is a produced artifact (fair to charge). Reactive → free/metered; proactive →
subscription. ₹0 → free; GPU → metered.

## The no-moving-up rule (hard, not a dial)

You may **never** move an item *up* from habit to paid to boost conversion. If "will this
fit me?" ever costs money, you haven't monetised the habit — you've destroyed the thing
building it and starved the data engine that feeds every paid feature downstream. The habit
layer stays free **even when it converts**, because its output isn't revenue, it's the asset.
`entitlements.classify_feature` defaults any unknown feature to free — when in doubt, free.

The conversion moment is engineered on the **render wall**, phrased as *creation, never
confidence*: "you've used your free renders today — want unlimited?" (fair, the toll is on
the made thing), never "pay to see if it fits" (a toll on the anxiety we exist to remove).

## Four fixes (build constraints for the token pass)

1. **fit-score is a standalone, free, unlimited action** — never only bundled inside a
   render, or "will this fit me?" is paywalled behind COST. It's the acquisition asset.
2. **save / skip / wear-log free and unmetered, forever** — they are the data flywheel;
   a token on them taxes the exact behaviour we cultivate.
3. **own-wardrobe render is on a tripwire** — half-price today (it feeds the wear-log);
   cut it to free if usage shows people avoiding it to save tokens. Doctrine outranks margin.
4. **scan-a-fit is metered (COST), not proactive (LAZYCOST)** — it's reactive; the scan is
   free, it's just a render from a different input.

## The currency — tokens, a permeable wall

Everything on the **paid** side (metered renders + subscription) is accessed by spending
**tokens**, not a hard cash paywall. Two families of faucet fill a wallet:

- **Earn — in-app gamification:** usage, saving, capture, streaks.
- **Earn — promotion / advocacy** (the additional options, on top of in-app): **referral**
  of friends, **RAAQ**, **broadcast** of a look, **PR / press** credited to the user, and
  **WhatsApp owned-media** app promotion. These grow Krey, so we pay the user in tokens.
- **Buy:** cash — but cash only ever buys **tokens** (bundles) or the **pass** as a shortcut.
  It is not a separate door: ₹999/yr KREY UNLIMITED = buying the same token pass a grinder
  earns. Every path runs through the one currency.

This keeps the wall **permeable**, which is the whole point for a 20–28 GenZ audience: no one
is hard-blocked, and because advocacy *earns the currency*, the growth engine and the token
faucet are the same act. Grind, promote, or pay — either way the user crosses. Both barriers
are token-governed: Barrier 1 spends tokens **per render**; Barrier 2 spends a token **pass**
for unlimited + proactive over a period. Cash is the fast lane, never the only lane.

The Habit Line still governs: **the habit stays token-free.** Tokens price only value *on
top* of the habit, never the fit answer or the free daily render.

**The numbers are SAMPLES, not economic law.** The locked reference map — `GRANT 100 /
DAILY 5 / OWNCOST 5 / COST 10 / LAZYCOST 15 / KREY UNLIMITED ₹999·yr` — is a placeholder to
reason with. Real values live in the **backend**, are **env-overridable** (`token_map()` /
`earn_map()` read `KREY_TOKEN_*` / `KREY_EARN_*`), and are **finalised once the app ships**
against measured per-render GPU cost + the free-tier subsidy we allow (Slice 4 benchmark).
The ₹999 tier especially is a bet unvalidated until that benchmark.

Already in code: `app/capture_tokens.py` (earn — grants held, then resolved by the cascade,
so garbage earns nothing), `app/eligibility.py` `TokenHold` + `insufficient_tokens` (spend —
reserved up front, committed on a successful render, released on failure),
`analytics.token(direction="earned"|"spent")` (both faucets are events), and
`entitlements.earn_map` (the earn-source taxonomy: in-app + promotion). The remaining build
is the full **token pass** — wiring promotion grants (referral/RAAQ/broadcast/PR/WhatsApp)
through the same grant-and-resolve pattern, plus the buy path and subscription tiers, settled
together with the final numbers.

**Economics (deferred, flagged):** earned-token renders still cost us GPU, so the earn rate
must be tuned against burn or gamified access blows the free-tier subsidy. When we model it,
split **bought-token renders** (revenue-funded) from **earned-token renders** (a subsidy
cost) — the subsidy model gets that split as a new input. Later, once GPU-seconds are real.

## Where it's enforced

`app/entitlements.py` holds the executable form: `classify_feature()` files every feature as
`free_habit`, `paid_metered` (Barrier 1), or `paid_proactive` (Barrier 2) with its barrier
number and reason — the single call any new surface passes through. `token_map()` and
`earn_map()` hold the SAMPLE, env-overridable amounts. Tests (`tests/test_entitlements.py`)
assert the confidence + ₹0 data ops can **never** resolve to paid — the no-moving-up rule,
guarded in code, not just prose.
