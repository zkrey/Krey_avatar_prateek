# Krey Avatar — Service A: twin extraction

The avatar sub-project's extraction backend. Deterministic, **no ML training, no GPU**.
Two slices fill the `body_models` record (Capture Pipeline Spec §4); each is proven
by a pure-math test suite before any expensive step.

| Slice | Endpoint | Fills | Core (tested, stdlib-only) |
|---|---|---|---|
| 1 · skin tone | `POST /twin/extract-skin` | `skin_tone` | `app/monk.py` |
| 2 · measurements | `POST /twin/extract-measurements` | `measurements`, `body_shape`, `accuracy_ledger` | `app/measure_core.py` |

## Slice 1 — skin tone

Photo → clean skin patches (forehead + cheeks) → CIELAB → nearest Monk swatch + a
confidence. Returns the `skin_tone` slice.

```
POST /twin/extract-skin   (multipart: file=<image>)
→ { "eligibility": {...}, "monk_tone": { "value": 6, "confidence": 0.9,
     "needs_confirm": false, "model": "deterministic-lab-mst-v0", ... },
    "detector": "mediapipe" }
```

No usable face → `eligibility.passed:false, quality_flags:["no_face"]` (retake path).

## Slice 2 — body measurements

Front-body photo + **declared height/weight/sex** (+ optional declared `body_type`) →
per-part measurements with per-field confidence, a computed body shape, and the
backend accuracy ledger.

```
POST /twin/extract-measurements
    (multipart: file=<image>, height=170, weight=65, sex=2, body_type=<optional>)
→ { "eligibility": {...}, "scale_px_per_cm": 2.121,
    "body_models": {
      "measurements": { "waist": { "width_cm": 25.0, "depth_cm": 19.5,
        "circumference_cm": 70.1, "depth_source": "estimated_no_depth",
        "confidence": 0.74 }, ... },
      "body_shape": { "shape": "...", "family": "...",
        "declared_crosscheck": { "agreement": true|false|null, ... }, "bmi": 18.4 },
      "accuracy_ledger": { "body_confidence": 0.81, "landmark_coverage": 1.0,
        "surfaced_to_user": false, "flags": [...] } } }
```

Design, per the spec + project guardrails:
- **Declared height is the scale anchor** — pixel-height (top-of-mask → heel) ÷ declared
  height gives px/cm. Declared `body_type` is only a **cross-check**; the computed shape
  is the source of truth and is never overwritten.
- **Per-field confidence (0–1)** blends landmark visibility, mask continuity, depth
  source, and anatomical plausibility.
- **Accuracy ledger (spec §6)** is backend-only (`surfaced_to_user: false`); it records
  landmark coverage (COCO-17), per-field confidence, an aggregate `body_confidence`, and
  flags a re-capture nudge below 0.60.
- **No GPU.** MediaPipe's pose landmarker runs on CPU; heavy deps (cv2/mediapipe/numpy)
  are imported lazily so the app and tests load without them.

Eligibility (account + verified DOB) is **not** checked in these endpoints — it lives at
the single `canRender` chokepoint (slice 3), never scattered per feature.

### Salvage / attribution

The slice-2 measurement algorithm (height-anchored scale, landmark-derived sample rows,
Ramanujan ellipse circumference, population depth ratios, anatomical guardrails, and the
body-shape taxonomy) is **adapted from the departed engineer's `zkrey/UserImageProcessingAPI`**
(`ProcessingSteps/BodyProcessing.py`). This repo adds the COCO-17 contract + coverage,
numeric per-field confidence, the declared-body_type cross-check, and the §6 accuracy
ledger, and wraps it all in the shared `body_models` contract.

`app/skin_tone.py` similarly holds candidate salvage points for her preprocessing
(LAB conversion, exposure filtering) — reconcile when convenient.

## Run locally

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                 # 16 deterministic tests, no photo/model needed

uvicorn app.main:app --reload
# slice 1:
curl -F "file=@face.jpg" http://127.0.0.1:8000/twin/extract-skin
# slice 2 (needs the pose model, below):
curl -F "file=@body.jpg" -F height=170 -F weight=65 -F sex=2 \
     http://127.0.0.1:8000/twin/extract-measurements
```

**Deploy to a live URL:** a `Dockerfile` builds the whole engine (deps + models). See
[`docs/DEPLOY.md`](docs/DEPLOY.md) for a step-by-step (Railway + Supabase, Mumbai region).
Quick local container: `docker build -t krey-service-a . && docker run -p 8000:8000 krey-service-a`.

**Runtime models (not bundled):** Service A uses three Google MediaPipe models
(Apache-2.0). They are large binaries, freely re-downloadable, and kept out of git.
Fetch them once per machine:

```bash
./scripts/fetch_models.sh          # downloads into ./models (the default MODELS_DIR)
```

| File | Endpoint | Purpose |
|------|----------|---------|
| `pose_landmarker_heavy.task` (~30 MB) | `/twin/extract-measurements` | body pose landmarks |
| `hair_segmenter.tflite` (~0.8 MB) | `/twin/extract-face` | hair mask → colour + texture |
| `face_landmarker.task` (~3.7 MB) | `/twin/extract-face` | iris landmarks → eye colour |

Point `MODELS_DIR` elsewhere if you keep them outside the repo. When a model is
absent its slice degrades cleanly (measurements → clear 503; face → composes whatever
else it can); the deterministic tests need none of them.

## Verified

- `tests/test_monk.py` — 5 tests over the LAB→Monk core.
- `tests/test_measurements.py` — 11 tests over the measurement core (scale anchor,
  circumference, per-field confidence, computed shape, body_type cross-check, landmark
  coverage, accuracy ledger, `body_models` composition).
- All 16 pass with stdlib only; heavy deps stay lazy, so real-photo validation of pose
  and face detection happens on a machine with the models present.

## Build sequence (spec §14)

- **Slice 1** ✅ skin tone · **Slice 2** ✅ measurement engine + accuracy ledger.
- **Slice 3** — eligibility cascade + `canRender` chokepoint + token-hold. Must exist
  before any GPU spend.
- **Slice 4** — benchmark generative try-on GPU-seconds; rebuild the cost model. *(costs
  money — gated on explicit permission.)*
- **Slice 5** — wire Service B (render worker + fit-score) behind `canRender`.
