# Krey — Creator Attribution & Revenue-Share (design note, for later)

_Captured 2026-10-03. **Not built** — this is the plan for after the social test validates the
loop. The point of writing it now: we're already logging the raw signals from day one, so the
ledger accrues even though none of the payout machinery exists yet. Don't paint us into a corner._

---

## 1. Thesis

People go sour when their effort isn't recognised. If Krey lets anyone generate a fresh fit /
idea and that idea later drives brand value, **the originator should get credit — and a cut**.
Credit is what turns casual users into repeat contributors; a revenue-share is what turns
contributors into a flywheel. NFT-like in the *useful* sense only: durable, verifiable proof of
**"who originated this,"** minus the speculative/token baggage. The mechanism is **provenance +
attribution → revenue share**, vetted through the backlink.

Two payout surfaces this enables later:
- **Referral bonus** — you invited someone who became active → you earn.
- **Creator/idea bonus** — you originated a fit/trend that others adopted or that a brand
  monetised → you earn from that lineage.

---

## 2. What already exists (the substrate — ~70% there)

We log the raw attribution signals today, so the credit graph is accruing now:

| Signal | Table / field | What it proves |
|---|---|---|
| Who created a look | `looks.owner_hint`, `looks.created_at` | originator of each fit |
| Invite graph | `referrals` (`referrer_hint`, `visitor_hint`, `source`, `activated`, `created_at`) | who brought whom, from which platform |
| Engagement per look | `garment_events` (`event_type` view/try/share, `garment_id`, `channel`, `session_hint`, `referrer_hint`, `created_at`) | downstream reach of a creation |
| Ranking lineage | `rank_sets.owner_hint`, `rank_votes` | which creations got peer traction |
| Confidence signal | `confidence_marks` | whether a creation actually moved someone |

**Gap:** these are keyed on `*_hint` (opaque per-browser ids), not accounts, and the shared
artifact (the image) doesn't carry a per-creation handle. So today we can *describe* lineage but
not *pay out* on it reliably.

---

## 3. The three things to add

### 3a. A per-look provenance handle (so attribution survives leaving the platform)
- A **short link per look**: `krey.app/l/<look_id>` (resolves to the look/ballot page, which
  already knows its `owner_hint`). Every click/re-render/conversion through it ties back to the
  originator server-side.
- The **visible watermark stays brand/discovery only** — it can't legibly carry a unique
  per-image code without clutter, and screenshots lose click-tracking. **The server-side
  provenance record is the source of truth, not the pixels.** (Optional later: a faint QR or a
  short per-look code in the watermark for screenshot-only cases — accept it's lossy.)

### 3b. Stable creator identity
- `owner_hint` (browser id) must be upgradeable to an **account** (email/phone/OAuth) before any
  money moves — you can't pay a localStorage string. Design: keep `owner_hint` as the join key,
  add an `accounts` table mapping `owner_hint[] → account_id` so pre-account contributions
  back-fill credit when someone signs up.

### 3c. The credit ledger (the payout source of truth)
A queryable graph: **creator → look → downstream events → conversions**. Sketch:

```
creations(look_id, creator_id, kind[fit|trend], created_at, parent_look_id?)   -- lineage/remix
attributions(event_id, look_id, actor_id, type[view|try|share|activation|purchase],
             platform, value_cents?, created_at)
credits(account_id, period, basis[referral|creator|remix], amount_cents, status)
```
`parent_look_id` captures **remix lineage** — if someone riffs on your fit, a share of the child's
credit flows up the chain (bounded, decaying per hop, so it doesn't explode).

---

## 4. Payout vetting ("backlink vetting")

Revenue share invites abuse, so credit must be **earned and verified**, not just claimed:

- **Real conversions only** — credit attaches to vetted downstream value (a verified activation, a
  brand-tracked purchase via a signed link/postback), never to raw view counts (trivially faked).
- **Anti-self-dealing** — drop attribution where `referrer_hint == visitor_hint`, same-device
  chains, or implausible velocity (N activations/min). Reuse the `session_hint` + IP + timing
  signals we already have.
- **Dedup & decay** — one credit per (actor, look, type) in a window; remix credit decays per hop
  and caps total payout at 100% of the realised value.
- **Brand-side truth** — brand revenue is only creditable when the brand confirms it (signed
  conversion postback / reconciliation), so payouts reconcile against real money, not estimates.
- **Hold + review** — credits land in `status=pending`, clear after a fraud window, pay out on
  review. Human-in-the-loop for large amounts.

---

## 5. Phasing

1. **Now (passive):** keep logging `owner_hint`, referrals, events. ✅ already doing it. Add
   `look_id` → `owner_hint` is already stored; nothing to change. **Do not** delete/rotate hints.
2. **Post-validation, if the loop spreads:** per-look short links + accounts (3a, 3b) — turns the
   hint graph into an identity graph.
3. **When a brand deal exists:** the credit ledger + vetting (3c, §4) — the actual accounting.
4. **Payout:** wallet/UPI/credits, tax/KYC, terms. Out of scope here; gated on real revenue.

---

## 6. Honest caveats

- **No money until accounts + a real revenue source exist.** Everything before that is just
  accruing a clean audit trail.
- **Screenshots are lossy** — a picture with only a visible URL credits the site, not the person.
  Accept that the *click/scan* path is the high-fidelity one; the watermark is discovery.
- **This is a post-product-market-fit feature.** Build it when the test proves people actually
  share and adopt each other's fits — not before. The only thing that matters *today* is that we
  keep the data accruing so we can back-date credit when we switch it on.

---

_See also: `UNIT_ECONOMICS.md` (what revenue has to cover before a share is possible),
`STACK.md` (where `owner_hint` / `referrals` / `garment_events` live)._
