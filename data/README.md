# data/ — open datasets for validation & calibration

Raw images are **not** in git (large + licence/consent-restricted — see `.gitignore`). This
folder holds the **registry**, and derived **reports** are committed under `reports/`. Full
rationale + per-source verdicts: [`docs/skin_data_plan.md`](../docs/skin_data_plan.md).

Skin tone is deterministic (`app/monk.py`, CIEDE2000), so these feed **validation +
calibration**, not training — except hair texture (the one classifier worth training; no
labels here yet).

## Layout
```
data/
  sources.json        # machine-readable registry (urls, labels, licences, use)  [tracked]
  reports/            # derived reports from bench/skin_report.py                 [tracked]
  <key>/              # raw images fetched locally                          [git-ignored]
```

## Workflow
1. **Fetch** what you need (needs the per-source CLI/token — kaggle, gsutil, gdown):
   ```
   ./scripts/fetch_datasets.sh dermacon_in indicfairface scin
   ```
2. **Report** — run Krey's real Monk reader over it and write a committed report:
   ```
   python -m bench.skin_report --data data/dermacon_in/images --name dermacon_in
   ```
   Writes `data/reports/dermacon_in.{json,md}` — tone distribution, needs_confirm /
   off-swatch rates, ΔE2000 stats, and (for Monk-labelled folders) agreement vs labels.
3. **Commit** the report (not the images). That's the "early info" kept for later.

> Use the **cv2/mediapipe** stack for real validation (the production skin extractor). Without
> it the harness falls back to a coarse PIL proxy, clearly flagged in the report. `reports/
> example_synthetic.md` is a format sample generated from solid swatch colours (not real data).

## Adopted vs skipped (summary — details in the plan)
- **Calibrate:** DermaCon-IN (Indian + Monk), SCIN (US + Monk, secondary).
- **Validate:** IndicFairFace (Indian faces, CC0/CC-BY).
- **Tool:** fairface-onnx (attributes; optional).
- **Skip:** IISCIFD (grayscale, non-commercial), the two coarse Kaggle skin-tone sets.

## Licence discipline
Confirm each licence before any product use — IISCIFD is non-commercial; SCIN/DermaCon-IN are
research/clinical (confirm commercial); Kaggle sets unclear. Same rule as the `buffalo_l`
research-only flag (`docs/scope_bakeins.md`). Never commit raw faces/skin images to git.
