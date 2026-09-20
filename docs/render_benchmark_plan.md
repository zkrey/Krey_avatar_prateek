# Render benchmark — the digital-twin "try-on" (Service B), step 0

The appearance twin (identity + skin + hair + eye) is live and validated on real testers.
The next milestone in the doctrine is **M1 render = generative try-on (Path B)** — "you, in a
garment." It's the GPU/cost piece, deliberately **parked until a benchmark proves it's worth
building**. This is that benchmark, run for **$0 on free Colab GPU** (since Sohan's local GPU
isn't soon).

**Goal:** answer one question before we build or host anything —
> Can an open generative try-on model put a garment on our user and keep them **recognisably
> themselves** (~85% likeness bet), fast enough and on a free/cheap GPU?

If yes → build Service B behind the existing `canRender` gate. If no → we've spent nothing.

## Approach
Image-based **virtual try-on (VTON)**, diffusion-based (matches "generative / Path B"; not 3D
— that's the M2 Blender premium). Input a **person image** + a **garment image**, output the
person wearing the garment.

### Model candidates (free-GPU first)
| Model | VRAM | Free Colab T4? | Quality | Use |
|---|---|---|---|---|
| **CatVTON** | ~8 GB | ✅ yes (fp16) | strong, light | **start here** |
| **OOTDiffusion** | ~10–12 GB | ⚠️ tight on T4 | strong | alternate |
| **IDM-VTON** | ~16–24 GB | ❌ needs A100/Colab Pro | best | when quality-bound |

Start on the **free T4 with CatVTON**; only reach for IDM-VTON (Colab Pro/A100) if T4-tier
quality misses the bar.

## Inputs
- **Person:** the alpha owner photo — the same `owner_thumb`/best frame `/capture/session`
  already picks. A clear, front-facing, roughly waist-up shot works best for VTON.
- **Garment:** a flat-lay or on-model garment image. Assemble a small **test set of 5–10
  person × garment pairs** (a couple of testers × a few garment types: tee, shirt, dress).
- Keep raw people images out of git (same rule as `data/`); the benchmark reads them locally
  in Colab.

## How we judge it (the bar)
1. **Identity preserved** — `bench/render_eval.py` scores the ArcFace cosine between the
   original person and the render (our *real* recognition). This is the ~85% likeness bet made
   measurable. Primary metric.
2. **Garment fidelity** — does the actual garment (colour, cut, print) land correctly? Visual
   check per pair.
3. **Speed** — seconds per render on the free T4 (feeds the cost/latency model).
4. **Fit** — does it run within free-tier VRAM without OOM?

**Pass** = identity cosine stays high across the set **and** the garment is clearly right
**and** render time is tolerable on a free/cheap GPU. Record the numbers, don't eyeball only.

## Run it
`bench/render_colab.py` is a **turnkey** cell-marked script to paste into Google Colab (Runtime →
GPU, free T4). It: checks the GPU, installs **CatVTON** + its DensePose/SCHP mask stack, builds
the pipeline once, renders each `(person, garment, cloth_type)` triple, saves outputs, and runs
`bench/render_eval.py` on each. The one model-specific call (`run_tryon`) is filled from CatVTON's
own `app.py` (repo `zhengchong/CatVTON`) — the checkpoint + mask weights auto-download on first
run. You only supply the test images and list the triples. Set `KREY_FACE_MODEL=buffalo_l` in
Colab so the scorer uses the accurate recognition model (Colab has the RAM).

Gotchas baked into the notebook (learned the hard way on a first run):
- **`cloth_type`** — CatVTON's AutoMasker needs the garment class per pair: `upper` (tee/shirt/
  top), `lower` (trousers/skirt), `overall` (dress/jumpsuit). Match it to each garment image.
- **torch pin** — CatVTON's `requirements.txt` pins `torch==2.4.0`, which Colab no longer serves.
  The install cell strips torch/torchvision/torchaudio and keeps Colab's own torch+CUDA; never
  let it reinstall torch.
- **`av` + detectron2** — the DensePose masker needs both and neither is in the pins; the install
  cell adds them (detectron2 builds from source, a few minutes). fp16 is forced (T4/Turing = no bf16).
- **Self-contained scorer** — the identity scorer is inlined in the notebook (InsightFace buffalo_l
  only), so the benchmark needs no private-repo checkout and survives a Colab runtime recycle.
- **Verify vs the current README** if CatVTON has moved — the API is faithful to app.py as of the
  fill, but VTON repos change.

### VERDICT: M1 PASSES — and real-world photos work (no ideal shots required)
Runs on real tester photos, scored with our own ArcFace:
- Group/party/angled full-frame → ~0.41 (FAIL); a reasonably-framed subject → **0.81 (PASS)**.
- A **full-body, arms-out, busy-background** shot scored **0.244 raw** — then **0.944** after a
  face-anchored **smart-crop**, on the *same photo*. Visual check: face clearly the same person,
  garment (print/cut/trim) correct, skin tone + lighting consistent.

The identity bet is **won**, and won the right way — the fix lives in the pipeline, not in demanding
a perfect photo. Key architectural fact: **CatVTON is a masked inpainter** — it only regenerates the
garment region, so face, hair, background and on-face skin **pass through the input untouched**. Most
"noise" (background, on-face texture/skin) therefore needs **no correction** for identity.

### The input conditioner (build test-first, measure each factor)
What actually needs handling, ranked by measured/likely impact — add each only when an ablation on
real photos moves the score (as smart-crop did, 0.24 → 0.94):
1. **Face size / framing** — face-anchored **smart-crop** to a 3:4 head-to-hips box (face ~20% of
   height). **Shipped** in `run_tryon` (benchmark) and the Modal `tryon` (production).
2. **Composite-back, mask-aware** — paste ONLY the garment-mask pixels into the full original, so
   face/**hands**/background stay the real photo. Fixes generative hand artifacts. **Shipped.**
3. **Pose** — the torso crop mitigates arms-out; extreme poses remain edge cases.
4. **Lighting / white-balance** (`app/whitebalance.py`) — add only if an ablation shows it helps
   outdoor colour casts.
5. **Face-restore** (CodeFormer/GFPGAN) — only if an input is genuinely blurry; the face is passed
   through, so usually unnecessary.
Plus an **input-quality classifier** (face size/count, blur, exposure) to route auto-fix vs a soft
"use a clearer one" nudge — never a hard reject (capture doctrine).

### Cost / speed (measured)
~40 steps → **~75–80 s/render on a free T4**. Tunable via steps; L4/A10G on Modal cut it further.
Feed seconds/render × GPU price into unit-econ before any always-on GPU.

### Garment × base-outfit matrix (6 renders, real + studio)
Identity held everywhere (id_cos 0.85–0.94) — smart_crop closed that variable. The remaining
question is *visual garment-fit*, which the (face-only) score can't see, so it's an eyeball call:

| Combo | id_cos | fit verdict |
|---|---|---|
| real_top (you, in a skirt) × top | 0.939 | ✅ clean |
| real_dress (you, in a skirt) × dress | 0.942 | ⚠️ awkward — floral read as a chest panel over the existing skirt |
| clean0_top / clean0_dress (studio, leggings) | 0.91 / 0.90 | ✅ / ✅ clean |
| clean1_top / clean1_dress (studio, jeans) | 0.86 / 0.85 | ✅ / ✅ clean |

**Ship rules that fall out:**
1. **The model is solid** — studio/clean inputs render uniformly clean on both tops and dresses.
2. **Tops (`upper`) are the reliable v1** — clean on real *and* studio inputs. Ship tops first.
3. **Render quality tracks garment↔base-outfit match**: clean when the target garment's coverage
   matches the base outfit's structure (top→separates, dress→simple base); mismatches (top over a
   full dress; dress over an existing distinct skirt) produce boundary/awkwardness. This is a
   **routing rule** (detect base outfit → offer matching garment types), not a model fix — it
   belongs in the subject router.
4. **B2B mirror is the quality sweet spot** — controlled studio inputs render cleanest, reinforcing
   B2B as the higher-quality, faster-to-revenue track.

### Coverage plan — bottoms + grey areas (next mapping pass)
Tops-first ships now; the matrix must be widened before broadening the catalog. Still to map:
- **Bottoms (`lower`)**: trousers/skirts — untested (CatVTON's bundled examples are upper/overall
  only; upload a lower-garment image to test). Confirm mask + fit behaviour.
- **Base-outfit detection → routing**: classify the person's current outfit (separates vs
  one-piece) and offer only matching garment types; the "grey" mismatches above are what this fixes.
- **Indian wear**: saree, kurta, lehenga, dupatta layering — key for the market, likely a distinct
  hard class.
- **Body/fit grey areas**: plus-size, maternity (bump preservation), very loose/tight garments.
- **Occlusions / pose**: holding objects, bags, crossed arms, non-frontal — measure degradation.
- **Input hygiene**: multi-person, no clear subject, extreme lighting → route to soft nudge, not a
  broken render.
Each is an ablation on real images: add the fix only where it moves the eyeball verdict (the same
measure-first discipline that took the crop from 0.24 → 0.94).

### Decision (parked): capture requirement differs by 2D vs 3D
The 5-image capture and the render are **two separate pipelines**. The 5-image capture
(`/capture/session` → `capture_core.py`) builds the *appearance twin* — owner-pick across frames,
identity confidence, and appearance fusion that lifts per-attribute accuracy ~65% (1 photo) → ~84%
(5 photos). It does **not** feed the renderer: CatVTON consumes exactly **one** person image, so
extra frames only give a better pool to auto-pick the single cleanest render base from
(`select_best_frames`), not richer render input.

- **Alpha (now):** keep the current multi-image capture as-is. It hardens the twin/owner-pick code
  under real test data and costs us nothing to leave running.
- **Launch flow (to apply on the actual prototype design, not the alpha harness):**
  - **2D render (M1):** require **one** clean single-person, front-on, waist-up photo; treat "add a
    few more to sharpen your twin" as optional/progressive, never a signup gate. Eases signup, still
    renders + gives a usable (lower-confidence) appearance read.
  - **3D mirror twin (M2):** multiple **angles** become a genuine requirement (reconstruction needs
    viewpoints) — the natural place to ask for more, when users are more invested.
- Net: don't change the alpha capture now; split the requirement (1-photo 2D vs multi-angle 3D) when
  reworking the real prototype signup.

## If it passes → the path (still cheap)
1. Wrap the render as a **Modal** serverless-GPU function (free monthly credits, scale-to-zero
   — pay only per render). See `docs/scope_bakeins.md` cost notes.
2. Add `/render` to Service A, **gated by the existing `canRender` eligibility + token hold**
   (already built) — no render without account/DOB and a token; garbage earns nothing.
3. Feed render speed + the identity/fidelity scores into the unit-economics model before any
   always-on cloud GPU.

## Cost & licence
- **$0** for the benchmark (free Colab). Modal free credits for the first hosted endpoint.
- **Confirm each model's licence before commercial use** — several VTON checkpoints are
  research-only (same discipline as `buffalo_l` / SMPL-X in `scope_bakeins.md`). Fine to prove
  the benchmark; swap for a commercially-licensed model (or licence it) before launch.
