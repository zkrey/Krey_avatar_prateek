# Krey — Render Ceiling Challenges & Frontier-Model Brief

_A running log of the capability ceilings we hit with the assembled open-source
render stack (CatVTON, SDXL+InstantID, Gemini/Nano-Banana), and what an owned,
from-scratch frontier model would need to solve them. Pull this when we build the
real thing._

_Last updated 2026-10-02._

---

## 0. The job to be done (what the model must actually do)
From a **casual, IG-native photo** (mirror selfie, arm-up, tilted, cropped, group,
seated, any lighting/background) + a **catalog garment image**, produce an image
that is:
1. **Recognizably the same person** (a true twin, not "someone similar").
2. **Wearing the actual garment** (exact colour/pattern/cut — not "the gist").
3. **Correctly fitted** to their real body/pose (drape, proportion, coverage).
4. **Fast** (seconds, not minutes) and **cheap at scale**.
5. **Consistent** (same inputs → same person across renders, for fair ranking).

No current open model does all five on casual input. The gaps below are the spec
for the model we'd build.

---

## 1. Observed ceiling challenges (with evidence from the alpha)

### C1 — Out-of-distribution (OOD) casual inputs
- **Seen:** a sideways (EXIF-rotated) mirror selfie → CatVTON split/garbled; arm-up
  selfies → smeared garment; angled/wide shots → wrong torso placement.
- **Root cause:** VTON/parsing models trained almost entirely on clean, front-on,
  full-body *studio catalog* photos. Casual poses are OOD → body parsing
  (DensePose/SCHP) mislocates regions → everything downstream fails.
- **Frontier requirement:** robust to in-the-wild inputs — any pose, crop, angle,
  occlusion, lighting, background, multi-person (pick the subject). No "stand like a
  catalog model" demand. This is the #1 product constraint: **adapt to the user,
  never change IG upload behaviour.**

### C2 — Garment fidelity (exact, not approximate)
- **Seen:** text-prompt garment (InstantID path) invented a different outfit
  (feather dress for a kurta); Nano-Banana needed to be *shown* the garment to get
  close.
- **Root cause:** a model that takes the garment only as text/embedding cannot
  reproduce the specific print/cut. Needs the garment **image** as a hard
  conditioning signal, with faithful texture/logo/neckline transfer.
- **Frontier requirement:** pixel-faithful garment transfer — colour, pattern,
  print placement, trims, silhouette — conditioned on the garment photo (and ideally
  multiple garment views / flat-lay + on-model).

### C3 — Identity preservation (a true twin)
- **Seen:** InstantID produced a generic person, not the user; identity collapsed
  especially when the face was small in frame.
- **Root cause:** one-shot face adapters are weak and degrade as the face shrinks in
  a full-body frame; the base model's own face prior takes over.
- **Frontier requirement:** strong identity lock across framings (face + body shape,
  hair, skin). Support **per-user fine-tune / embedding** (a few photos → a durable
  identity token) for a real twin, not a lookalike.

### C4 — 2D warp vs 3D body understanding
- **Seen:** elongated neck, stretched torso, "melted" collars (CatVTON 2D
  warp+inpaint).
- **Root cause:** CatVTON stretches a flat garment into a 2D mask — no 3D body or
  cloth model, so it can't truly drape.
- **Frontier requirement:** implicit/explicit **3D body + garment geometry** so
  fabric drapes and fits by body shape and pose (true fit, not a decal).

### C5 — Coverage change & skin synthesis
- **Seen:** flagged — saree/long-sleeve input, short/sleeveless target exposes skin
  the photo never showed.
- **Root cause:** VTON inpaints the garment region; newly-exposed skin must be
  *synthesized*, and CatVTON has no way to be told the person's tone.
- **Frontier requirement:** synthesize newly-exposed body (arms/legs/midriff)
  matching the person's **measured skin tone** (we already compute Monk MST + LAB/RGB
  — feed it as a conditioning input, not just a text clause) and body shape.

### C6 — Garment & body diversity (non-Western, all bodies)
- **Seen:** Indian ethnic sets (kurta, salwar, dupatta, saree) render worse than
  Western tops — they're under-represented in training data.
- **Frontier requirement:** training data spanning ethnic/cultural garments,
  intimates, drapes (saree/dupatta), layering, and the **full range of bodies, skin
  tones, ages, genders**. This is a data-sourcing + licensing problem as much as a
  modelling one.

### C7 — Multi-piece / full sets
- **Seen:** full "overall" sets rendered the top but mangled the salwar/skirt (no leg
  canvas on a torso crop); fixed partially with cloth-type-aware cropping.
- **Frontier requirement:** compose a **multi-garment outfit** (top + bottom +
  dupatta/layers) coherently on the body in one pass.

### C8 — Latency, cold-start & cost at scale
- **Seen:** 172s and 344s CatVTON renders on cold T4 (serverless scale-to-zero +
  ~5GB model load + 40 steps). Nano-Banana ~15–30s but paid per image + closed.
- **Frontier requirement:** sub-5s inference, warm-poolable, cheap per render at
  scale; a model sized/distilled for real-time (step-distilled / cached identity +
  garment embeddings so repeat renders are fast).

### C9 — Background / scene control
- **Seen:** InstantID invented chaotic abstract backgrounds; CatVTON keeps the real
  one (good for honesty, limiting for "wow").
- **Frontier requirement:** controllable background — keep the real scene *or*
  place a clean/branded/aspirational backdrop, on demand.

### C10 — Consistency & reproducibility
- **Why it matters:** the ranking thesis needs fair comparison — the *person* must be
  constant across looks so voters judge the garment, not render noise.
- **Frontier requirement:** deterministic identity/body across a user's looks; only
  the garment varies. Seedable, stable embeddings.

### C11 — Closed-vendor dependency & data privacy
- **Seen:** Nano-Banana is closed, paid, per-image, and sends user body photos to a
  third party — a real concern for a body/identity product; also vendor
  pricing/availability risk.
- **Frontier requirement:** an **owned** model we can run in our infra, fine-tune,
  and keep user data private — the strategic reason to build rather than rent.

---

## 2. What a from-scratch frontier model needs

### Data (the real moat)
- Large, licensed, **diverse** person×garment dataset: in-the-wild poses + paired
  garment images; ethnic/intimate/layered garments; all bodies/tones/ages/genders.
- Paired supervision where possible (same person, same garment, multiple poses) +
  synthetic augmentation (3D render farm) for coverage/drape.
- Per-user capture spec already drafted (see `docs/body_data_plan.md`,
  `docs/skin_data_plan.md`, capture pipeline) — reuse for identity fine-tune data.

### Architecture (candidate direction)
- Diffusion/transformer backbone that jointly conditions on: **identity embedding**
  (per-user), **garment image(s)**, **body/pose (3D-aware)**, **skin-tone**, and a
  **scene/control** signal.
- Garment branch with faithful texture transfer (IP-Adapter-style but trained in, not
  bolted on); identity branch supporting per-user fine-tune/LoRA.
- Step-distilled student for real-time inference.

### Evaluation (build the harness early)
- **Identity:** face-embedding cosine vs. the real person (target > threshold).
- **Garment fidelity:** garment-region similarity (colour/pattern/structure) vs. the
  catalog image.
- **Fit/realism:** human pref + anatomical checks (no extra limbs, correct drape).
- **Robustness:** score across an OOD casual-input test set (selfies, angles, groups,
  lighting) — the thing current models fail.
- **Latency/cost per render.** Track all of these per model version.

### Infra / scalability
- Warm GPU pools (no cold-start tax), autoscaling, embedding caches (identity +
  garment precomputed), CDN for outputs.
- Owned + private: user body data never leaves our infra.

---

## 3. Reuse from the current build (don't rebuild these)
- **Ranking/confidence engine** — `app/rating.py` (Glicko-2, Bradley-Terry,
  Plackett-Luce, Kendall's τ). The moat; model-agnostic.
- **Monk skin-tone** — `app/skin_tone.py` + `app/monk.py` (deterministic CIELAB /
  ΔE2000). Feed as a conditioning input to the new model.
- **Coverage / pose** — `app/coverage.py`, `app/measurements.py` (MediaPipe) for
  auto-crop/subject-detection and input routing.
- **Catalog + taxonomy** — Supabase schema (`docs/catalog_schema.sql`),
  cloth_type/segment/subsegment, ingestion notebook.
- **Capture specs** — `docs/body_data_plan.md`, `docs/skin_data_plan.md`,
  `docs/hair_texture_plan.md` — the data-capture groundwork.

## 4. Interim strategy (until the owned model exists)
- Treat the render engine as a **commodity**: use the best available (Nano-Banana for
  IG-native/quality, CatVTON as a free fallback for clean body shots), auto-routed.
- Bend the app to the user: auto-orient (done), auto-crop to subject, no gating/
  nagging, auto-route by input.
- Invest energy in the **ranking/confidence/network-effect** layer (the defensible
  part), and in **data capture** that will train the owned model later.

---

_Append new ceilings here as we hit them (date + symptom + root cause + requirement)._
