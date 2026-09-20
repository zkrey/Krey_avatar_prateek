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

### First-run finding (single-person input is non-negotiable)
The first real run showed a bimodal result: group/party/angled photos scored ~0.41 (FAIL) while a
cleaner single subject scored **0.81 (PASS)** with the garment landing correctly (right colour/cut).
Same model, same scorer — the only variable was input quality. Takeaways:
- The identity bet is **alive**: on a reasonable single subject CatVTON keeps the person
  recognisably themselves *and* applies the garment. The failures were off-spec inputs, not the model.
- **Product implication:** the render-capture UX must enforce a **single-person, front-on, roughly
  waist-up** shot. A face that is a tiny fraction of a full-body/group frame gets softened by the
  768×1024 inpainting; a proper waist-up crop keeps the face large enough to preserve.
- Still to confirm on a clean solo capture: the identity score and a face clean enough to skip a
  face-restore pass. If a restore is needed later, add CodeFormer/GFPGAN after the render.

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
