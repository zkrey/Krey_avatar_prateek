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

**PAID — value on top of the habit:**
1. **Leverage** — the *same* habit made frictionless: unlimited renders (quota) and
   priority/warm speed. The user isn't buying a feature they lacked; they're buying *more
   and faster* of the habit they already love. These are the two levers already built
   (`entitlements.PLANS` → quota + lane).
2. **New value** — capabilities that only matter *because* the habit is in place, and that
   add something genuinely new rather than withholding a piece of the core: shareable HD
   exports, wardrobe/occasion planning, styling intelligence, shop-the-look, early drops,
   and — as the M2 **premium** layer — Sohan's photoreal 3D try-on (mesh + Blender, Path A),
   gated on the M1 rule fit-score reaching ~85% precision (docs/scope_bakeins.md). The 2D
   try-on builds the habit and stays free; hyperreal 3D is new value on top of it, never a
   replacement for it. Each new-value feature is admitted to the paid side **only if it
   passes the test below** — never by carving a slice out of the free habit.

## The test (apply to every new feature)

Ask one question: **does this build the habit, or create new value on top of it?**

- Builds the habit / removes forced cost → **free**. No exceptions, even under conversion
  pressure.
- Creates new value that presupposes the habit → **paid** (leverage or new-value).
- Can't tell → it's probably core to the habit; default it **free**. When in doubt, free.

The conversion moment is engineered, not gated: a free user hits the habit's *wow
inflection*, then meets the leverage wall (quota/speed) or is offered a new-value layer —
at the peak of wanting more, never before the habit has formed (`entitlements.upsell_signal`).

## How this sits with the earlier rule

The earlier decision — *"same product for everyone; free and paid differ only on quota and
speed"* — is not overturned; it is **the free side of this line**. The habit core is
identical for all and given away. This doctrine adds the principled way to introduce paid
value *above* the core: leverage (the quota/speed levers, unchanged) and, over time,
new-value layers — each one classified by the test, none of them a crippled piece of the
habit.

## Where it's enforced

`app/entitlements.py` holds the executable form: `FEATURE_LEDGER` classifies every known
feature as `free_habit`, `paid_leverage`, or `paid_new_value` with a reason, and
`classify_feature()` is the single call any new surface passes through. A test
(`tests/test_entitlements.py`) asserts the habit-core features can **never** resolve to
paid — the invariant, guarded in code, not just prose.
