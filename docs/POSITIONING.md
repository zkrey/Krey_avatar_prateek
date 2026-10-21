# Krey — Positioning: the consideration gradient (go-to-market thesis)

_Captured 2026-10-21 from a founder observation: "this product is for fast fashion where
people don't need to think deep before buying; for festive buying people may prefer a store
visit for quality + texture checks." This doc turns that into a positioning model. It is a
**strategy/GTM view**, not a build spec — it says where Krey wins outright, where it is a
bridge, and the one product lever that follows. Sits alongside `WARDROBE.md` (build thesis),
`ATTRIBUTION.md` (creator commerce), `SOCIAL_FLOW.md` (the loop)._

---

## The real axis is consideration, not category

The instinct ("fast fashion vs festive") is directionally right but the clean cut is
**consideration level = price × how much the fabric *feel* matters**, not a category label.
A ₹500 tee and an ₹8,000 lehenga sit at opposite ends of the same axis; "festive" is just
where high price and high tactility usually coincide.

Krey answers three of a buyer's four questions, at **every** point on the axis:

| Buyer question | Krey answers it? | Note |
|---|---|---|
| Will it **suit me** / my complexion? | ✅ try-on + tone profile | *more* important for a ₹8k outfit, not less |
| Will **my people** approve? | ✅ ask-your-people loop | festive is the **peak** of social validation |
| What **size** fits me? | ✅ `/fit/recommend` + `/fit/quick` | honestly flagged as an estimate |
| How does the **fabric feel** / is the quality real? | ❌ needs hands | the one genuine online gap |

So the limit isn't "festive" — it's the **tactile question**. Everything else Krey does
holds (and the social-validation job is *strongest* exactly at the festive end, because
festive outfits are bought to be seen and approved by family/friends).

## Where Krey wins outright vs. where it's a bridge

- **Low consideration (fast fashion / everyday) → own the whole funnel.** Discover → try on
  → size → **buy online**. The hard ROI story: fast fashion's real pain is **return rates
  from fit/looks uncertainty**, and Krey's try-on + size directly cut that — value to the
  retailer, not just a nice-to-have.
- **High consideration (festive / ethnic / premium) → be the de-risker, not the replacement.**
  Don't fight the store trip; make it **confident and short**: _try 10 looks at home →
  shortlist the 2 that are most you and that your circle loved → go feel those._ Krey becomes
  top-of-funnel + a de-risker. A pre-sold, correctly-sized, socially-validated buyer is
  exactly what a premium retailer wants walking in.

**Honest caution — it's a gradient, not a wall.** Festive/ethnic *is* sold online at scale in
India (FabIndia, Myntra, Ajio). What blocks more of it going online is **confidence +
returns** — Krey's whole value. So Krey lifts festive *both* ways: more confident online buys
**and** more confident store visits. Don't over-rotate to "festive = store only."

## The product lever this implies

One adaptive change, not a repositioning: **an adaptive "buy" CTA chosen by price/category.**

- cheap / fast-fashion item → **Buy online** (full funnel).
- festive / premium item → **Find in store · Reserve to try · Book a fitting**, with
  **fabric/texture close-ups + care/quality info** surfaced to narrow the tactile gap.

Same try-on / social / size core; only the **last step** differs. This keeps one product
while serving both ends of the axis honestly.

## How it hooks what we already have / are building

- **Texture content → `CATALOG_INGEST.md`.** The crawler already pulls *images + textures +
  info* off seller sites. That is precisely the asset that shrinks the "can't feel it" gap
  for festive and makes the reserve-to-try handoff credible. The texture-fidelity bar for
  multi-garment render (`WARDROBE.md` §hard-parts) is the same work paying off here.
- **Size honesty → `/fit/quick` + `size_charts.json`.** The estimate is flagged as an
  estimate and the brand-exact path exists; for festive/premium that naturally routes to
  "try the perfect fit/feel in store" rather than over-promising online.
- **Social validation → `SOCIAL_FLOW.md`.** Strongest at the festive end; the ask-your-people
  loop is the reason a festive buyer shortlists before visiting.
- **Commerce / attribution → `ATTRIBUTION.md`.** The reserve-to-try / store handoff is still
  an attributable conversion event — credit the creator/broadcaster whether the purchase
  closes online or in store.

## Parked for later — B2B "mirror tech" (revisit when that discussion opens)

> Deferred at founder's note (2026-10-21): _"we can later review once the mirror tech
> discussion begins for b2b."_ Not in scope now; captured so it isn't lost.

The festive store-visit is the one place the tactile gap bites — and it's also where a
**Krey in-store "mirror" (B2B)** could close the loop: the same try-on/social/size core served
on an in-store screen, so the shopper gets Krey's "does it suit me + what size" layer *at the
rack*, then feels the fabric in hand. That would make Krey the layer on **both** sides of the
handoff (at-home shortlist → in-store mirror), and turns the de-risker framing into a B2B
retail product rather than only a consumer app. **Revisit this section — and the
reserve-to-try handoff above — when the mirror-tech / B2B conversation begins.**

---

_See also: `WARDROBE.md` (create → broadcast → earn), `ATTRIBUTION.md` (credit + payout),
`SOCIAL_FLOW.md` (friend = validation, follow = discovery), `CATALOG_INGEST.md` (textures +
seller inventory), `UNIT_ECONOMICS.md` (render costs)._
