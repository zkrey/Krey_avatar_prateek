# Alpha → render rollout — two gated steps

The plan from alpha twin-testing to the first real render benchmark. Each step is **gated
on the previous one succeeding**, so we never spend GPU (or money) before the read is trusted.

## Step 1 — Alpha twin read (now, GPU-free)

Alpha users run **`/alpha`** (Twin Check): add ≤5 photos → Krey picks the owner and reads
skin tone, hair, eye, body shape, proportions (+ cm measurements when height is given). Every
value carries confidence; low-confidence ones ask a one-tap confirm; anything wrong is flagged
to the team via `/feedback`.

**Exit criterion (what "positive feedback" means):** the read is *recognisable* — flag rate
per attribute is low and confirms dominate, i.e. we're at/above the provisional **~85% likeness**
bet (`docs/recognition_thresholds.md`). Skin within **ΔE ≲ 2–3**; shape/proportions accepted;
measurements' wide error bars understood (they're estimates, not fit-grade yet). No GPU spent —
the pipeline stops at the render wall.

## Step 2 — Local-GPU render benchmark on Sohan's machine (only after Step 1 passes)

Once the twin read is trusted, stand up the **generative render (Service B) locally on Sohan's
GPU** to measure the two numbers that price the whole economy: **render speed** and **render
accuracy** — before renting any cloud GPU.

Pieces that already exist to make this a setup-and-measure task, not new R&D:
- **`docs/local_render_setup.md`** — version-locked CatVTON + detectron2/DensePose setup
  (Win11 / Ubuntu), the exact env that runs a try-on render locally.
- **`bench/gpu_benchmark.py`** — the benchmark harness, including a **`local` provider**
  (`LocalProvider`) that logs a self-hosted render's wall-clock GPU-seconds into the same shape
  as the cloud (Replicate) provider. One command; captures per-render seconds + warm/cold.
- **`docs/DOCTRINE.md` → "First measurement"** — the cost model this feeds: GPU-seconds ×
  $/sec × FX → cost/render → validates (or resets) the ₹999 tier and the Barrier-2 resetting cap.

**What Sohan captures:**
1. **Speed** — wall-clock GPU-seconds per render (warm vs cold), at a couple of resolutions
   (e.g. 768×576 and higher), logged via `bench` `local` provider.
2. **Accuracy** — does the try-on look right on the twin (garment drape, identity preserved)?
   Qualitative + the M1 rule fit-score cross-check; this is the gate for the **M2 3D** path
   (unlocks at ~85% fit-score precision, `docs/render_approaches.md`).
3. **Cost estimate** — plug local GPU-seconds into the DOCTRINE cost math to get a real
   cost/render and a defensible free-tier subsidy, replacing the n=1 Replicate estimate.

**Exit criterion:** a measured cost/render + render latency the UX can hide behind the instant
free fit answer, and accuracy good enough to show. That's the go/no-go for a cloud GPU + the
metered render wall going live.

## Why this order

Doctrine: the fit answer is instant and free, so a slower render sits behind an answer the user
already has — we can afford to measure render economics deliberately. Testing the read first
(Step 1) means we only pay for GPU (Step 2) once users confirm the twin is worth rendering.
