# Krey Avatar — Service A (twin extraction)

The avatar sub-project's **digital-twin backend**: a FastAPI service that turns photos
into a compact `body_models` record (skin tone, hair, eye, body measurements, recognition
score), plus the fit-score engine, the eligibility/`canRender` gate, the token economy, and
a served **team QA console** at `/tester`. GPU-free (CPU only); the generative render
(Service B) is parked — see `docs/backend_status.md`.

## Repository map

| Dir | Contains |
|---|---|
| `app/` | FastAPI backend (`main.py`) + extraction pipelines; `webtest.html` = the `/tester` QA console. |
| `app/config/` | Tunable JSON: fit, cascade, recognition, size charts, texture. |
| `docs/` | Status, doctrine, scope, deploy, feedback loop, branching SOP, render notes. |
| `bench/` | GPU-cost benchmark harness. |
| `tests/` | Backend test suite (pure-math + endpoint). |
| `models/` | Runtime MediaPipe models (git-ignored; fetched via `scripts/`). |
| `scripts/` | `fetch_models.sh` and helpers. |

## Branches

**`main` is the single source of truth** — the complete app. Deploy from `main`; branch
from `main`. All earlier working branches (`feat/*`, `claude/*`) were consolidated into
`main` and retired — do not revive them or push parallel copies.

Naming for new branches: `type/scope-detail`. The full scheme + workflow is in
**[`docs/BRANCHING_SOP.md`](docs/BRANCHING_SOP.md)** (and `CONTRIBUTING.md`).

## Endpoints (Service A)

The live API is defined in `app/main.py`; the QA console at `/tester` exercises all of it.

| Area | Endpoints |
|---|---|
| Twin (single photo) | `POST /twin/extract-skin`, `/twin/extract-face`, `/twin/extract-measurements` |
| Consolidated flows | `POST /capture/session` (identity/owner-pick), `/body/measure`, `/capture/instagram` |
| Twin store | `GET`/`DELETE /twins/{user_id}` |
| Fit & style | `POST /fit/recommend`, `/style/profile` |
| Economy & ops | `POST /render/authorize`, `/feedback`, `GET /health`, `GET /tester` |

Design invariants (height is the measurement scale anchor; declared `body_type` is a
cross-check only; the accuracy ledger is backend-only; eligibility lives at the single
`canRender` chokepoint, never per-feature) and the **current build status + test count**
live in **`docs/backend_status.md`**. The free/paid model is in `docs/DOCTRINE.md`.

## Run locally

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                 # pure-math suite runs without cv2/models
uvicorn app.main:app --reload
# QA console:    http://127.0.0.1:8000/tester
# skin:          curl -F "file=@face.jpg" http://127.0.0.1:8000/twin/extract-skin
# measurements:  curl -F "file=@body.jpg" -F height=170 -F weight=65 -F sex=2 \
#                     http://127.0.0.1:8000/twin/extract-measurements
```

Heavy deps (cv2 / mediapipe / insightface) are lazy-imported, so the pure-math tests and
the app load without them; endpoint tests and the real pipelines need the full stack.

## Deploy

A `Dockerfile` builds the whole engine (deps + MediaPipe models baked in + InsightFace
`buffalo_l` pre-warmed for the identity algo). Deploy **`main`**. Step-by-step (Railway +
Supabase, Mumbai region): [`docs/DEPLOY.md`](docs/DEPLOY.md). Quick local container:
`docker build -t krey-service-a . && docker run -p 8000:8000 krey-service-a`.

**Runtime models (not bundled)** — three Google MediaPipe models (Apache-2.0), large and
freely re-downloadable, kept out of git. Fetched at image build; locally:
`./scripts/fetch_models.sh` (into `./models`, the default `MODELS_DIR`).

| File | Endpoint | Purpose |
|------|----------|---------|
| `pose_landmarker_heavy.task` (~30 MB) | `/twin/extract-measurements`, `/body/measure` | body pose landmarks |
| `hair_segmenter.tflite` (~0.8 MB) | `/twin/extract-face` | hair mask → colour + texture |
| `face_landmarker.task` (~3.7 MB) | `/twin/extract-face` | iris landmarks → eye colour |

When a model is absent its slice degrades cleanly (measurements → clear 503; face →
composes whatever else it can). The pure-math tests need none of them.

## Salvage / attribution

The measurement algorithm (height-anchored scale, landmark-derived sample rows, Ramanujan
ellipse circumference, population depth ratios, anatomical guardrails, and the body-shape
taxonomy) is **adapted from the departed engineer's `zkrey/UserImageProcessingAPI`**
(`ProcessingSteps/BodyProcessing.py`). This repo adds the COCO-17 contract + coverage,
numeric per-field confidence, the declared-`body_type` cross-check, and the §6 accuracy
ledger, wrapped in the shared `body_models` contract. `app/skin_tone.py` holds candidate
salvage points for her preprocessing (LAB conversion, exposure filtering).
