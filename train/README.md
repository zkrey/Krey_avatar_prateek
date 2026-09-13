# train/ — hair-texture classifier (optional, off the runtime path)

The one classifier worth training for the twin: **hair texture** (straight / wavy / curly /
coily) — the last recognition gap (90% → 100%). Rationale + data verdicts:
[`docs/hair_texture_plan.md`](../docs/hair_texture_plan.md).

Nothing here is imported by Service A at runtime. Torch is an **optional** dependency; the
trained model plugs in via `train/infer.py` only when present, and everything degrades to
"unavailable" without it (exactly today's behaviour).

## 1. Get the data
```
./scripts/fetch_datasets.sh hair_type_kavyasree      # -> data/hair_type_kavyasree/ (git-ignored)
```
Source classes are Curly / Straight / Wavy / **Kinky** / **Dreadlocks**. Training remaps them
automatically: **kinky → coily**, and **dreadlocks/braids/bald dropped** (styles, not
textures). Unknown folders are dropped too. Not Indian — see the fairness gate below.

## 2. Train
```
pip install -r train/requirements-train.txt
python -m train.hair_texture --data data/hair_type_kavyasree --out models/hair_texture
```
Transfer-learns ResNet18 → a 4-class softmax head (CrossEntropy). Saves the best-val
checkpoint to `models/hair_texture/model.pt` and `metrics.json` (overall + **per-class**
accuracy). CPU works; a GPU is faster. Flags: `--epochs --batch-size --lr --val-split`.

## 3. Fairness gate (before you trust it)
The training data is **not Indian**. Curly/coily are where biased models fail, so **do not
ship** until per-class accuracy holds up on **Indian** hair:
- hand-label a slice of **IndicFairFace** (Indian faces, no texture labels) as an eval set, and/or
- use **alpha `/alpha` flags** where users corrected a wrong texture (real Indian ground truth).

## 4. Wire it in
Set the env var and add one line to `app/face.py`'s hair path:
```
KREY_HAIR_TEXTURE_MODEL=models/hair_texture/model.pt
```
```python
from train.infer import read_hair_texture
hair_texture = read_hair_texture(hair_region)   # np.ndarray | PIL.Image | path
# -> {"value": "wavy", "available": True, "confidence": 0.83}
```
It returns the exact `hair_texture` slot shape, so `recognition_from_body_models` picks it up
and coverage goes to 100%. No model / no torch → `{"available": False}` and the score
renormalises as it does now.

## Licence
Confirm the training set's licence before commercial use (same discipline as buffalo_l /
SMPL-X, `docs/scope_bakeins.md`). Model weights are yours; the data terms are not.

## Priority
Post-M1 polish, not a launch blocker (the twin is recognisable at ~90% without texture).
Pairs naturally with Sohan's Step-2 GPU setup (`docs/alpha_render_rollout.md`).
