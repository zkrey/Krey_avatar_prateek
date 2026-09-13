# Skin & face data plan — do we need to train on Indian faces?

Short answer: **for skin tone, no training is needed** — the reader is deterministic
(`app/monk.py`: photo → CIELAB → nearest Monk swatch by CIEDE2000 + continuous tone). What we
lack is **validation / calibration data** (Indian faces with trustworthy tone ground truth),
not training data. Training only earns its keep for the parts that are genuinely ML:
**hair texture** (unbuilt classifier — the last recognition gap), a possible **illumination
corrector** for skin, and a **licence‑clear identity model** to replace research‑only
InsightFace `buffalo_l`.

> A classifier that predicts a discrete Monk *bucket* (the folder‑per‑class / `ImageFolder`
> pattern) is the **wrong tool** for our skin read: it re‑introduces the coarse‑bucket bug we
> fixed with continuous tone, and ImageNet resize/normalise destroys the colour/exposure a
> colorimetric read depends on. Keep skin deterministic; measure and calibrate it.

## What we actually need

1. **Validation set — Indian faces, real lighting.** To measure our reader's behaviour and
   robustness across the population (not n≈2). IndicFairFace covers this.
2. **Calibration ground truth — skin patches with a known tone.** To measure ΔE‑vs‑reality
   and set `OFF_SWATCH_DE` / recognition weights / the ~85% bet
   (`docs/recognition_thresholds.md`). Needs a **colour reference in frame** (grey/white card)
   or expert Monk labels. SCIN gives Monk labels (caveated); the rest we build.
3. **Hair‑texture labels** (coily/curly/wavy/straight) — the only genuinely train‑worthy gap
   for the twin. **None of the sources below have these.**
4. **Licence‑clear identity model** — to replace `buffalo_l` before commercial launch
   (`docs/scope_bakeins.md`).

## Assessment of the curated sources

| Source | What | Indian faces | Skin‑tone labels | Faces vs other | Licence | Use for Krey |
|---|---|---|---|---|---|---|
| [IndicFairFace](https://github.com/aarishshahmohsin/IndicFairFace) | 14,400 Indian faces, state+gender balanced (36 regions) | ✅ strong | ❌ none | faces | CC0 / CC‑BY / public‑domain | **ADOPT** — Indian‑face validation corpus |
| [DermaCon‑IN](https://arxiv.org/abs/2506.06099) ([Kaggle](https://www.kaggle.com/datasets/hiro002/dermacon-in-dataset)) | 5,450 clinical derm images, 3,002 **South‑India** patients (NeurIPS 2025) | ✅ **Indian** | ✅ **Monk + Fitzpatrick** (centred MST 6–7) | dermatology, **not faces** | confirm (research/clinical) | **ADOPT (caveated)** — the best **Indian + Monk‑labelled** skin for calibrating LAB→Monk on our actual population |
| [SCIN](https://github.com/google-research-datasets/scin) (also on [HF](https://huggingface.co/datasets/google/scin)) | 10k+ dermatology images, US, crowdsourced | ❌ US | ✅ **Monk (eMST)** + Fitzpatrick | skin conditions, **not faces** | SCIN Data Use License (confirm commercial) | **ADOPT (caveated)** — Monk‑label calibration for the LAB→Monk map (non‑Indian, so secondary to DermaCon‑IN) |
| [fairface‑onnx](https://github.com/yakhyo/fairface-onnx) | ONNX **model** (race‑7/age/gender) | — (model) | ❌ | model, no data | code MIT, weights CC‑BY 4.0 | **OPTIONAL tool** — coarse attributes; does NOT replace ArcFace identity; no skin colour |
| [IISCIFD](https://github.com/harish2006/IISCIFD) | ~1,650 Indian faces (251 publishable), N/S + age/wt/ht/gender | ✅ | ❌ | faces, **grayscale** | research‑only, **non‑commercial** | **SKIP** — grayscale kills colour; non‑commercial |
| [Kaggle · adityakammati](https://www.kaggle.com/datasets/adityakammati/skintone-dataset) | generic skin‑tone images | ❓ not Indian‑specific | coarse (unclear) | mixed | unclear | **SKIP/low** — coarse classes, wrong tool |
| [Kaggle · usamarana](https://www.kaggle.com/datasets/usamarana/skin-tone-classification-dataset) | skin‑tone, White/Brown/Black | ❌ | 3 coarse classes (not Monk) | mixed | unclear | **SKIP** — wrong granularity, not Indian |

### How the adopted ones plug in
- **IndicFairFace →** run `app/monk.py` (+ face/identity) across it to (a) confirm owner‑pick /
  recognition works on diverse Indian faces, (b) inspect the *distribution* of continuous
  tones and the `needs_confirm` / off‑swatch rate, (c) find failure lighting. It has **no tone
  ground truth**, so it validates robustness/coverage, not absolute ΔE. Licence is friendly.
- **DermaCon‑IN →** the preferred **Indian** Monk/Fitzpatrick calibration reference: check our
  LAB→Monk mapping against dermatologist‑adjacent MST labels on **Indian** skin (its MST 6–7
  centre matches our target population). Caveats: dermatology sites not faces, lesion/condition
  confounds on colour, South‑India skew, and confirm the licence (research/clinical dataset)
  before any product use.
- **SCIN →** same idea on a larger but **US** population — use as a secondary cross‑check of
  the mapping, after DermaCon‑IN. Access via the GCS bucket (GitHub) or the `google/scin`
  HuggingFace mirror. Caveats: not faces, US not Indian, layperson MST, its own Data Use
  License.

## What's still missing (build it)

The ideal set — **Indian faces + trustworthy tone ground truth across lighting** — doesn't
exist in the list. Build it cheaply:
- **Alpha flags** (`/alpha` → email) are labelled disagreements per attribute — the seed set.
- Add a **colour reference** to a subset of captures (a grey card or known object) so a
  subset has true colorimetry to anchor ΔE.
- For **hair texture**, source a curly/wavy/straight‑labelled set separately (none here);
  that's the one place the `ImageFolder`/CNN training pattern is the right tool.

## Licence caution (before anything ships)
- IndicFairFace **CC0/CC‑BY** — fine commercially with attribution. ✅
- IISCIFD **non‑commercial** — do not ship. ❌
- SCIN — its own **Data Use License**; confirm commercial terms before product use.
- FairFace weights **CC‑BY 4.0** (attribution); it's an attribute model, not identity.
- Kaggle sets — per‑dataset licence unclear; verify before use.
- Same discipline as the `buffalo_l` (research‑only) and SMPL‑X flags in `docs/scope_bakeins.md`.

## Tooling (in the repo)

- **Registry:** `data/sources.json` — every source with url, labels, licence, and use.
- **Fetch:** `scripts/fetch_datasets.sh <key>` — pulls each into `data/<key>/` (git-ignored;
  raw faces/skin images are never committed).
- **Report:** `python -m bench.skin_report --data data/<key>/images --name <key>` — runs the
  real Monk reader and writes `data/reports/<key>.{json,md}` (tone distribution, needs_confirm
  / off-swatch rates, ΔE2000 stats, and agreement vs Monk labels when present). Reports are
  committed — that's the "early info" kept for later. `data/reports/example_synthetic.md` shows
  the format. See `data/README.md`.

## Recommendation
1. **Validate now** on **IndicFairFace** (Indian‑face robustness + tone distribution), and
   calibrate the LAB→Monk mapping on **DermaCon‑IN** (Indian + Monk) with **SCIN** as a
   secondary cross‑check — no training.
2. **Seed the real calibration set** from alpha flags + a colour‑reference capture.
3. **Train only** where it's warranted: **hair texture** (needs a labelled set not in this
   list) and, later, an illumination corrector / licence‑clear identity model.
4. **Skip** IISCIFD and the two Kaggle sets for skin (grayscale / coarse / non‑Indian / licence).
