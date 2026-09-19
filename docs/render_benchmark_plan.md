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
`bench/render_colab.py` is a cell-marked script to paste into Google Colab (Runtime → GPU, free
T4). It: checks the GPU, installs the model, renders each person × garment pair, saves outputs,
and runs `bench/render_eval.py` on each. Set `KREY_FACE_MODEL=buffalo_l` in Colab so the scorer
uses the accurate recognition model (Colab has the RAM).

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
