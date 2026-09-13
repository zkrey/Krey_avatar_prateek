# Krey backend — status update (2026-08-26)

**Repo:** `zkrey/Krey_avatar_prateek` · branch `main` (canonical) · **272 tests passing.**

## ✅ Built — Service A (the digital-twin backend), GPU-free
- **Skin tone** — photo → Monk scale (1–10) + confidence. Verified on a real selfie (Monk 6, 0.87).
- **Hair colour** — nearest natural swatch (LAB) + confidence + "dyed/coloured" flag. Deterministic, GPU-free.
- **Eye colour** — nearest swatch with the **Indian dark-brown prior** + confidence. Deterministic, GPU-free.
- **Body measurements** — pose keypoints + declared height → per-part measurements + confidence + accuracy ledger. Verified on a real body image (all 17 landmarks, sensible cm).
- **Eligibility gate** — one `canRender` wall: no account/DOB → blocked; **jurisdiction-keyed age policy** (India-only for M1; minors blocked even with consent); render-cost **token hold**.
- **Input cascade** — screens junk/unsafe photos cheapest-first (device → CPU) *before* the GPU; **capture-token anti-spam** (garbage earns 0).
- **Fit-score** — "does it fit?" rule engine (no GPU). Now **fit is measurement × preference**: fitted/true/relaxed/oversized, **per garment** → outfit combos; "try a size up/down" grading. Runs on real sample size charts.
- **Analytics** — every action emits a structured event (the spine + funnel), guest→user stitch, `gpu_seconds` for cost, social events schema-ready for M2. Wired into the live endpoints.
- **Recognition score** — the §6 "is this recognisably them" number in the record (backend-only, drives re-capture). Coverage now **90%** (skin + hair + eye + landmarks); only hair-texture remains.

## 🔑 Key decisions locked
- **M1 render = generative (Path B)** + rule fit-score. **3D/Blender (Sohan) = M2 premium**, gated on the M1 fit-score hitting **~85% precision + fast on-phone render**.
- **Two accuracy axes:** twin *likeness* ~85% is fine (recognisable, not a mirror); product *fit* must be **exact** (misfit disliked unless asked).
- Forward-scope (M2 social · B2B in-store · scan-a-product · analytics) requirements captured in `docs/scope_bakeins.md`.

## ⏳ Not built yet
- **The render (Service B, generative try-on)** — the visual "you in a garment" + RAAQ. It's the GPU/cost piece; **parked** until a real GPU (local Intel integrated GPU can't run it). First step is a small paid benchmark.
- **Hair texture** (straight/wavy/curly/coily) — the last recognition gap (90% → 100%); a small **single-label** classifier (not colour maths), plan + datasets in `docs/hair_texture_plan.md`. Hair *colour* + eye *colour* are done. The one place training is warranted; post-M1 polish, not a launch blocker.
- Dashboard / discovery / taste engine — broader app (master spec), separate workstream.

## Data & validation
- **Skin tone is deterministic (no training)** — CIELAB → Monk by **CIEDE2000**, with the
  off-swatch ΔE folded into confidence + the §6 recapture nudge (`app/monk.py`,
  `app/recognition.py`). What we need is **validation/calibration**, not a training set.
- **Recognition targets + the ~85% bet vs the literature:** `docs/recognition_thresholds.md`.
- **Open datasets assessed + wired:** `docs/skin_data_plan.md` + `data/` — registry
  (`data/sources.json`), fetch (`scripts/fetch_datasets.sh`), and a report harness
  (`bench/skin_report.py` → `data/reports/`). Adopt DermaCon-IN (Indian + Monk) + SCIN to
  calibrate the mapping, IndicFairFace to validate on Indian faces; raw images stay out of git.
- **Alpha tester is the ground-truth instrument:** `/alpha` (`docs/alpha_hosting_guide.md`)
  emails each flag; the flag/confirm distribution recalibrates the thresholds on real users.
- **Body shape is deterministic too** (`measure_core.classify_body_shape`); Indian
  anthropometrics (IndiaSize) calibrate size charts + plausibility ranges, not a model —
  `docs/body_data_plan.md` + `bench/body_shape_report.py`.
- **Hair texture** is the one train-worthy slice — scaffolded in `train/`, wired env-gated
  into `app/face.py` (`docs/hair_texture_plan.md`).

## Money
Nothing spent. Everything above is free/CPU. The only paid step ahead is the one-off GPU render benchmark, which we'll do deliberately.
