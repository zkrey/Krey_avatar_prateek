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

## Fit is measurement × PREFERENCE (not one "correct" size)
Users wear a size by preference, not just measurement (measured M but wears L — baggy taste,
weight fluctuation). So the fit-score carries a `fit_preference` (fitted|true|relaxed|oversized)
that shifts the target ease, **applied per garment** — so outfit combinations (baggy top + baggy
bottom, fitted top + relaxed bottom) are just per-piece preferences. `grade_sizes()` grades every
size (tight / true to size / relaxed / oversized) to power a "try a size up/down" view where the
user picks the look on purpose. Declared preference now (cold-start); learned from what they keep/
wear later (V2 revealed taste). Offsets live in `app/config/fit.json` (uncalibrated placeholders).

## Reconciliation flag — Sohan's 3D-mesh + Blender fit work
The sub-project spec **locked** M1 render = generative (Path B) + **rule-computed** fit-score, and
**deferred** 3D mesh + cloth-sim + Blender (Path A) to M2 (premium / made-to-measure), because a
per-garment 3D asset doesn't scale to open inventory and was the original blocker. If Sohan's
Blender/3D work is intended as the **M1 fit engine**, it conflicts with that locked decision and
duplicates the rule fit-score. If it's intended as the **M2 fit-truth / premium** engine, it's
complementary — it just fills the same fit contract later.

**RESOLVED → M2.** Sohan's 3D work is deferred to M2, **gated on the M1 rule fit-score reaching
~85% precision with a fast on-phone render** (so the UX doesn't collapse). His repo
`zkrey/blendertemplateclothing` currently holds only two Blender clothing-template scenes
(men/women `.blend`); no SMPL-X / pipeline / NN code yet. Integration seams: (1) `body_models`
measurements → SMPL-X shape betas; (2) shrink-wrap garment-vs-body distances → the `fit_score`
contract as `method:"mesh-fit-v1"`. Licences to confirm before deep work: **SMPL-X** (commercial
licence), **YOLO** (AGPL — prefer YOLOX / RT-DETR), and the **DLR** model (unidentified — get the link).

## Capture session: identity vs. current-appearance (timestamps + ageing)

The 5-photo capture is not just redundancy — it runs **two aggregations on the same set**:

- **Identity (stable):** pool the face fingerprint across ALL frames (old + new) to lock
  "same person" at high confidence. This is what lets us salvage a multi-face / messy
  frame — find the recurring face, treat it as the user — instead of hard-rejecting.
  Reject only when there is genuinely no consistent face; otherwise soft one-tap reconfirm.
- **Current appearance (time-varying):** attributes that DRIFT with age/lifestyle —
  above all **body build**, and to a lesser extent hair — must be **recency-weighted**.
  The freshest photo (latest timestamp) anchors the "current build"; older frames
  corroborate identity but count less toward how the twin looks *now*.

Mechanics to honour:
1. **Read EXIF `DateTimeOriginal`** per photo; order the set by recency. This is the
   ageing signal — validates the user isn't building a twin from only decade-old photos,
   and drives the recency weighting above.
2. **Fallbacks (important):** EXIF is frequently stripped — WhatsApp, screenshots,
   social re-saves lose it. When a timestamp is missing: fall back to file mtime if
   plausible, else treat the photo as undated (corroborates identity, does NOT anchor
   "current"). Never silently assume "now."
3. **Build needs a body in frame.** Face selfies alone can't give build — that comes from
   the measurement (body) slice. So "current build" = most-recent frame that actually
   contains a torso, recency-weighted. Keep the face-session and body-session timestamps
   linked on the body_models record.
4. **Future refresh:** when the user later connects social networks, the same
   recency-weighted appearance update runs on newly dated photos to keep the twin current.
   Design the aggregator so a later photo can update appearance without re-proving identity.
