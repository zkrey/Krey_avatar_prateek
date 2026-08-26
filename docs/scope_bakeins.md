# Krey — forward-scope bake-ins (M2 / B2B / scan / analytics)

Decisions captured now so the twin backend doesn't need painful retrofits later.
Source: master spec backend handoff, analytics instrumentation spec, B2B in-store spec,
avatar sub-project spec. **These are requirements to honour, not code to build yet** —
except where a slice is already touching the area.

## Scope map
| Track | What | When |
|---|---|---|
| M1 (consumer) | twin build → try-on (owned free / new token-gated) → discover/style → tokens | now |
| M2 (social) | validation/creator layer (RAAQ, tried-on, creator rail) + commerce scale | post-MVP |
| B2B in-store | *same* twin+VTO engine as magic-mirror / tablet / **SDK in retailer app** | parallel, after M1 |
| Scan-a-product | scan a garment in the wild → try it on | M1 entry-point; own model later |

The B2B spec is explicit: *"B2B is a distribution play, not new R&D — the engine, avatar
accuracy and wardrobe logic carry straight over."* So the twin **is** the B2B product —
provided the boundaries stay clean.

## Bake-ins (cheap now, expensive to retrofit)

1. **Analytics event layer — Phase-1 dependency, NOT a backfill** ("the gates are the events").
   - Every backend action emits a structured event carrying the common **spine**:
     `user/guest_id, session_id, ts, surface, entry_point, region, signed_in, app_version, device`.
   - Must-have events touching our backend: `avatar_build` (start/done/abandon + duration_s —
     "the gate for everything"), extraction events, `render_*` carrying **`gpu_seconds`**
     (feeds cost-per-render + ₹999 validation), `confirm_viewed/abandoned` (token gate).
   - **Guest events stitch onto `user_id` at signup** (pre-account funnel not a black hole) —
     doubly important for B2B in-store guests.
   - **Social/creator events: define the schema now, fire in M2.**

2. **Ephemeral "guest twin" mode.** B2B in-store + guest-preview need a short-lived, no-account
   body model (QR → ~30-sec capture) alongside the consented-retained consumer path
   (the two privacy regimes, sub-project spec §10). The twin builder must not assume an account.

3. **Garment input is source-agnostic.** A garment may come from `catalog | wardrobe | scan`
   (and B2B: a retailer's SKUs). Fit-score + render inputs carry a `source` and treat all alike,
   so scan-a-product and B2B catalogs slot in without new plumbing.

4. **Stable IDs** — `twin_id`, `render_id`, `look_id` — so the M2 social layer can reference
   renders/looks without a rebuild.

5. **Region carried in records + events** (Indian-first is the moat; analytics slices by region).

## Fit-score contract note (see §Sohan below)
The M1 fit answer is a **rule engine** (measurements × garment metadata) per sub-project spec §5.
Its OUTPUT contract — `{verdict: fits|snug|size_up|size_down, regions[], confidence, method}` —
is defined so a future **3D-mesh fit-truth** engine (Path A, deferred to M2 premium/made-to-measure)
can produce the SAME shape and slot in behind the same interface. Rule engine = `method:"rule-fit-v0"`;
a mesh engine would be e.g. `method:"mesh-fit-v1"`. Callers depend on the contract, not the method.

## Reconciliation flag — Sohan's 3D-mesh + Blender fit work
The sub-project spec **locked** M1 render = generative (Path B) + **rule-computed** fit-score, and
**deferred** 3D mesh + cloth-sim + Blender (Path A) to M2 (premium / made-to-measure), because a
per-garment 3D asset doesn't scale to open inventory and was the original blocker. If Sohan's
Blender/3D work is intended as the **M1 fit engine**, it conflicts with that locked decision and
duplicates the rule fit-score. If it's intended as the **M2 fit-truth / premium** engine, it's
complementary — it just fills the same fit contract later. His code is not on GitHub yet, so this
must be confirmed with him before either path is treated as M1-critical.
