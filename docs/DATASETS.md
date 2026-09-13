# Datasets index — validation, calibration & the one thing to train

One page for Sohan. The principle first: in Krey, **skin tone and body shape are
deterministic** (`app/monk.py` CIEDE2000, `app/measure_core.py` ratios) — so open datasets
feed **validation / calibration**, *not* training. The **only** thing worth training is
**hair texture**. Full rationale + per-source detail in the three plans:
[skin](skin_data_plan.md) · [hair](hair_texture_plan.md) · [body](body_data_plan.md).
Machine-readable registry: [`data/sources.json`](../data/sources.json).

## All sources at a glance

| Source | Domain | Indian? | Tone labels | Verdict | Why |
|---|---|---|---|---|---|
| [IndicFairFace](https://github.com/aarishshahmohsin/IndicFairFace) | faces | ✅ | — | **VALIDATE** (skin/identity) | 14.4k Indian faces, CC0/CC-BY; run our reader across it |
| [DermaCon-IN](https://www.kaggle.com/datasets/hiro002/dermacon-in-dataset) | dermatology | ✅ | **Monk + Fitzpatrick** | **CALIBRATE** (skin) | best **Indian + Monk** labels → tune LAB→Monk |
| [SCIN](https://github.com/google-research-datasets/scin) | dermatology | ❌ US | **Monk + Fitzpatrick** | **CALIBRATE** (secondary) | large Monk set, US population |
| [Hair Type (kavyasreeb)](https://www.kaggle.com/datasets/kavyasreeb/hair-type-dataset) | hair | ❌ | — | **TRAIN** (texture) | the one train-worthy set; remap kinky→coily, drop dreadlocks |
| [IndiaSize](https://www.scribd.com/document/850449371/indiasize) | anthropometry | ✅ | — | **CALIBRATE** (body) | Indian size charts + plausibility ranges |
| [Indian Anthropometric Dimensions](https://www.scribd.com/document/511496232/INDIAN-Anthropometric-Dimensions) | anthropometry | ✅ | — | **CALIBRATE** (body) | secondary anthropometric reference |
| [fairface-onnx](https://github.com/yakhyo/fairface-onnx) | model | — | — | **TOOL (optional)** | race/age/gender model; not identity, not skin |
| [IISCIFD](https://github.com/harish2006/IISCIFD) | faces | ✅ | — | **SKIP** | grayscale (no colour) + non-commercial |
| [Kaggle adityakammati](https://www.kaggle.com/datasets/adityakammati/skintone-dataset) | skin | ❓ | coarse | **SKIP** | coarse classes, not Monk, not Indian |
| [Kaggle usamarana](https://www.kaggle.com/datasets/usamarana/skin-tone-classification-dataset) | skin | ❌ | White/Brown/Black | **SKIP** | 3 coarse classes, not Monk |

## What to actually do

1. **Skin** — `./scripts/fetch_datasets.sh dermacon_in scin indicfairface` →
   `python -m bench.skin_report --data data/<key>/images --name <key>`.
   Calibrate on DermaCon-IN (Indian + Monk), cross-check on SCIN, validate robustness on
   IndicFairFace. Target: skin ΔE ≲ 2–3 ([recognition_thresholds](recognition_thresholds.md)).
2. **Body** — export IndiaSize/BIS tables to CSV → `python -m bench.body_shape_report --csv
   data/indiasize/adults.csv --name indiasize`. Recalibrate `size_charts.json`,
   `PLAUSIBLE_CIRC_CM`, `DEFAULT_DEPTH_RATIO`. Never prior an individual by ethnicity.
3. **Hair (train)** — `./scripts/fetch_datasets.sh hair_type_kavyasree` →
   `python -m train.hair_texture --data data/hair_type_kavyasree --out models/hair_texture`.
   Then `KREY_HAIR_TEXTURE_MODEL=models/hair_texture/model.pt` turns it on (already wired into
   `app/face.py`). **Fairness gate:** confirm per-class accuracy on Indian curly/coily first.

## Rules (all sources)
- Raw images are **never committed** — fetched into `data/<key>/` (git-ignored); only the
  registry + derived `data/reports/` are tracked.
- **Confirm each licence** before commercial use (IISCIFD non-commercial; SCIN/DermaCon-IN
  research; Kaggle unclear) — same discipline as `buffalo_l` / SMPL-X (`scope_bakeins.md`).
- The **alpha `/alpha` flags** are the real Indian ground truth over time — the datasets
  bootstrap; the users calibrate.
