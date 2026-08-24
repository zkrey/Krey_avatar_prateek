# Krey Avatar — Service A · Slice 1: skin-tone extraction

The first, cheapest slice of the avatar sub-project (see `krey_avatar_subproject_spec.html`,
build sequence §14). Deterministic, no ML training, no GPU. It proves the whole toolchain —
API shape, deploy, contract — on the lowest-risk piece before anything expensive.

## What it does

Photo → clean skin patches (forehead + cheeks) → CIELAB → nearest Monk swatch + a
confidence. Returns the `skin_tone` slice of the `body_models` record (spec §4).

```
POST /twin/extract-skin   (multipart: file=<image>)
→ { "eligibility": { "passed": true, "stage": 2, "quality_flags": [] },
    "monk_tone": { "value": 6, "confidence": 0.9, "confirmed_by_user": false,
                   "delta_e": 3.1, "dispersion_lab": 4.2, "needs_confirm": false,
                   "n_samples": 5, "model": "deterministic-lab-mst-v0" },
    "detector": "mediapipe" }
```

No usable face → `eligibility.passed:false, quality_flags:["no_face"]` — that's the
hand-off point to the eligibility cascade's retake path (spec §6, Stage 0/1).

## Verified

- `app/monk.py` — the LAB→Monk core — is unit-tested and **passing** (`tests/test_monk.py`,
  5 tests): each swatch classifies to itself at high confidence; light+dark spread trips
  `needs_confirm`; white maps to LAB L≈100.
- All modules syntax-clean. Heavy deps (mediapipe/opencv) are imported lazily, so the app
  loads without them — you validate face detection on a **real photo** in Claude Code.

## Run locally

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                 # the deterministic proof, no photo needed
uvicorn app.main:app --reload
curl -F "file=@face.jpg" http://127.0.0.1:8000/twin/extract-skin
```

Face detection: MediaPipe FaceMesh preferred; falls back to OpenCV's built-in Haar
cascade so it still runs if mediapipe isn't set up yet.

## Continue in Claude Code (the persistent home)

This chat's sandbox is throwaway — no keys, no deploy. In Claude Code on your machine:

1. Drop this folder into the repo (once Mick's Git links arrive, alongside them).
2. `pip install -r requirements.txt`, run the tests, then run the server and POST a real
   selfie — confirm the Monk value and the `needs_confirm` behaviour on your own photos.
3. Deploy the endpoint (E2E / Modal / Render) — this is the "prove deploy" half of slice 1.

Then, in order (spec §14):

- **Slice 2** — measurement engine: 17 keypoints + declared height → proportions, plus the
  accuracy ledger. Completes Service A. Still no GPU.
- **Slice 3** — eligibility cascade (Stage 0/1) + token-hold. Must exist before any GPU spend.
- **Slice 4** — benchmark generative try-on GPU-seconds on one E2E L4; rebuild the cost model
  and validate ₹999. Gate on every cost number.
- **Slice 5** — wire Service B (render worker + fit-score) behind `canRender`.

Note: `app/skin_tone.py` also holds candidate salvage points for Mick's
`zkrey/UserImageProcessing` (LAB conversion, exposure filtering) — reconcile when the repo lands.
