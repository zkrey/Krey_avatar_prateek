# Krey — Wardrobe, Custom Fits & Creator Commerce (build thesis, planned)

_Captured 2026-10-05. This is **core build thesis**, not a side feature: users digitise their
wardrobe, create custom fits, broadcast them, and **earn from the purchases those fits drive**.
It fuses the wardrobe idea + attribution/revenue-share (`ATTRIBUTION.md`) + the social graph
(`SOCIAL_FLOW.md`) into one loop. Not built yet; sequenced after the social loop is validated._

---

## The thesis: the fit is the unit

Today a "look" is something you try on and get your circle to react to. The build thesis makes
the **fit a first-class, shoppable, attributable object**:

> **Create → Broadcast → Earn.**
> A user creates a custom fit (from their own wardrobe + Krey trends) → broadcasts it (to their
> circle for validation, and wider for inspiration) → people discover and **shop the items in
> it** → the originator **earns an incentive from the resulting purchases**.

Every user becomes a creator *and* an affiliate. The thing they already want to do — put
together a great outfit and show it off — is the same action that drives commerce and pays them.

## Why it's core, not a bolt-on

It makes the three loops we've already designed converge on one object (the fit):
- **Social loop** (`SOCIAL_FLOW.md`): friends validate the fit (trusted, intimate); followers
  discover it (inspiration, reach). Follow = the discovery/shopping funnel; friend = the trust.
- **Attribution loop** (`ATTRIBUTION.md`): provenance says *who created* the fit and *whose
  broadcast* drove each view → purchases attribute back → creator gets paid (vetted).
- **Commerce loop** (new): each garment in a fit links to a buyable SKU; a purchase through the
  fit is the revenue event the incentive is a share of.

## Building blocks

| Block | What it does | Reuse / new |
|---|---|---|
| 1. Capture & cut-out | user photographs each garment; background-removed to a clean shot | Nano "isolate garment on white" — reuse render |
| 2. Auto-catalogue | Gemini vision tags each item (type, colour, pattern, formality, season) | reuse `garments` schema + taxonomy; **new per-user `wardrobe` table** |
| 3. Stylist / composer | proposes custom fits from the wardrobe (+ trends) that actually work | new (rules for constraints + LLM for taste) |
| 4. Multi-garment render | renders a full outfit (top+bottom+layer) on the user | reuse Nano; **de-risk: multi-item fidelity is the hard part** |
| 5. Shoppable tagging | links each garment to a buyable SKU / affiliate link | **new** — needs a product/affiliate source |
| 6. Attribution + payout | credits the fit's creator + the broadcaster; vets purchases; pays out | reuse `ATTRIBUTION.md` ledger + vetting |

## The hard parts (de-risk before committing)

1. **Multi-garment render fidelity** — we render one garment today; a full outfit is several
   composited. Prototype this first (does Nano hold top+bottom+layer convincingly?).
2. **Where buyable SKUs come from** — affiliate networks, brand partnerships, or a marketplace.
   No commerce loop without a product source + buy links. This is a BD/partnership dependency,
   not just code.
3. **Cross-platform attribution** — a fit broadcast off-platform (WhatsApp/IG) must still tie a
   purchase back to the creator. Reuse the per-look short link + provenance record in
   `ATTRIBUTION.md`; accept screenshots are lossy (visible watermark is the floor).
4. **Fraud / vetting** — real-money incentives invite abuse; credit only on vetted conversions,
   drop self-dealing (see `ATTRIBUTION.md` §4).

## Phasing (dependencies gate this)

1. **Now / M1:** prove the social loop (share → circle validates → OOTD). Keep logging
   `owner_hint` + referrals so provenance accrues.
2. **M2:** accounts + follow/friend graph (`SOCIAL_FLOW.md`) — required before any payout
   (can't pay a localStorage id) and before wardrobe is personal.
3. **M3 — Wardrobe & custom fits:** blocks 1–4 (upload → auto-catalogue → compose → render a
   full outfit on you). Ship as utility first, feeding the same share loop.
4. **M4 — Creator commerce:** blocks 5–6 (shoppable SKUs + attribution ledger + payout). Gated
   on a product/affiliate source and the attribution ledger being live.

**Recommended first concrete step (whenever we start):** a throwaway prototype of blocks 1–2
(upload → Gemini auto-tag → personal catalogue) **and** a multi-garment render test, to prove
the two riskiest pieces before building the rest.

---

_See also: `ATTRIBUTION.md` (credit + revenue-share mechanics + vetting), `SOCIAL_FLOW.md`
(friend = validation, follow = inspiration/discovery), `UNIT_ECONOMICS.md` (render costs)._
