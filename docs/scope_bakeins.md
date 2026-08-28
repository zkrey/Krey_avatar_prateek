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

## Face-recognition model licence (identity matching)

Identity matching (clustering the same face across the capture session) needs a
purpose-built face-recognition embedding — a general image embedder is far too weak
(measured 0.06 separation vs 0.60 for ArcFace on the founder's own decade of photos).
Development uses **InsightFace `buffalo_l`** (SCRFD detect + ArcFace embed + age/gender).
**Licence flag: InsightFace pretrained models are research / non-commercial.** Fine to
develop and prove against; **before commercial launch, swap to a licence-cleared model**
(commercially-licensed ArcFace weights, a self-trained embedder, or a paid face API —
AWS Rekognition / Azure Face / Face++). Same licence-gate discipline as SMPL-X / YOLO.
Estimated age is a noisy per-face cross-check only; the real ageing signal is the EXIF
timestamp.

## Paid / premium face-detection tier (revisit with team)

Founder note: keep a **paid high-quality face-reader** on the roadmap as a tiering lever,
not just a licence fix. Where the economics justify per-call cost:
  - **Subscription tier:** premium users get the paid high-accuracy detector/embedder.
  - **B2B / in-store:** magic-mirror & retailer SDK can carry a paid face API (accuracy
    and SLA matter more, volume is controlled).
Free/open model stays the default for M1 consumer scale. Decision to make WITH the team
once we reach the quality-tier stage: which paid vendor (AWS Rekognition / Azure Face /
Face++ / a licensed ArcFace), price per call, and where the tier line sits. This also
resolves the InsightFace non-commercial licence flag for the paid surfaces.

## Skin-tone illumination robustness — what worked, what didn't (measured)

Two people of visibly different complexion both bucketed Monk 6 (the coarse-label bug,
fixed by carrying continuous tone). The per-frame skin swing that remained was then
attacked two ways, measured on the founder's two real collections:

- **Per-frame white balance — did NOT help.** grey_world and white_patch on a face crop
  INCREASED the spread (skin-dominated crop has no reliable neutral; they fight the
  skin's real warmth) and shifted the mean. A sclera-referenced version was within noise
  (std 0.26->0.23) and only fired when eye-white was visible (~60-75% of frames). Kept as
  a tested tool (`app/whitebalance.py`) but NOT wired into the default pipeline.
- **Outlier-robust aggregation — worked.** The real cause was outlier FRAMES (one dark
  L*~32 shot), not a uniform cast. Rejecting frames >3 MAD from the median tone
  (`aggregate_numeric(robust=True)`) halved the spread (her 2.22->1.33) while keeping the
  two people distinct (you 5.68 vs her 6.17). This is wired for skin.

Lesson for other attributes: prefer robust aggregation over per-frame colour correction
unless a genuine, locatable neutral reference exists.

## Body measurement: two findings from the first real body capture

Ran the identity-anchored body pipeline on the founder's own single-person full-body
photos (height placeholder). Two things surfaced:

1. **Casual full-body photos still measure with huge variance.** Anchoring worked (7/8
   frames measured the user, one correctly gated `incomplete_body`), and the consolidated
   values were plausible (waist ~81, chest ~103 cm, BMI 23.5, Rectangle) — BUT per-frame
   spreads were 45-59 cm, so every field flagged needs_confirm and the decision was
   `reconfirm`, confidence ~0.33. Cause: different distance / pose / clothing / partial
   framing per photo, which the height-scale anchor can't normalise. **Implication:**
   fit-grade measurement needs a GUIDED capture (fixed distance, straight-on, arms
   slightly out, fitted/minimal clothing, full body in frame), not "pick any photos".
   Casual-photo aggregation gives a central estimate with wide error bars, not exact fit.
   This is the measurement analog of "face aggregates from casual photos; build does not".

2. **MediaPipe segmentation-mask native abort on certain frames.** One image
   (1600x721) hard-aborts the process inside MediaPipe's pose segmentation-mask output
   (`Check failed: 1 == ChannelSize()`), even single-pose; masks-off avoids it. It's a
   SIGABRT, not catchable in-process. **Hardening needed:** run the pose pass per image
   in an isolated subprocess so one bad frame is skipped, not fatal to the whole capture.

## The regular-user lazy path (on-device album) — device vs server split

Personal IG/Photos auto-fetch is dead (platform APIs removed it). The lazy path that
survives for regular users is on-device album access. Division of labour:

DEVICE (mobile app — not this backend):
  - One OS photo-library permission tap (normal mobile gesture).
  - Use the OS's own face grouping (iOS Photos / Android ML Kit) OR a small on-device model
    to gather the user's face cluster (or a one-tap "this is me" on a cluster).
  - Upload only that cluster / a sample — other people's photos ideally never leave the phone.

SERVER (built): the same capture pipeline does the picking —
  - owner found by face-dominance; auto-select the owner's BEST frames
    (capture_core.select_best_frames: top quality, freshest always kept) for the reads;
  - OWNER-ONLY RETENTION: only the owner is profiled; every other identity is discarded
    with the raw pixels and never returned (analyze_capture retention block reports counts);
  - recency-weighted, outlier-robust attribute fusion as before.

So "user does nothing, Krey picks" is real: even if the device uploads a broad chunk, the
server keeps only the owner's best frames and bins the rest. The device-side model + the
one-tap permission UI are the remaining MOBILE build; the backend half is done.
