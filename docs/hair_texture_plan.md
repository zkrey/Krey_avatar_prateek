# Hair texture — the one classifier worth training

Hair **texture** (straight / wavy / curly / coily) is the **only unbuilt slice** of the twin
and the last recognition gap: filling it takes coverage **90% → 100%** (`config/recognition.json`
weights it 0.10). Unlike skin tone and hair *colour* — both deterministic already
(`app/monk.py`, `app/hair.py`) — texture isn't colour maths, so this is the **one place
training earns its keep** (`docs/skin_data_plan.md`).

## The contract to fill (don't change it)
`app/face.py` already leaves a `hair_texture` slot and a stub
(`hair.texture_features_from_region`). The model must return that slot's shape so the rest of
the pipeline picks it up with no other change:
```
hair_texture = {"value": "wavy", "available": True, "confidence": 0.83}
```
`recognition_from_body_models` reads it when `available` is true and it lifts coverage to 100%;
when the model is absent it stays `{"available": False}` and the score renormalises (today's
behaviour). Low confidence → `needs_confirm`, same soft-confirm doctrine as every other slice.

## Single-label, not multi-label (scope)
The shared PyTorch snippet uses multi-label `BCEWithLogitsLoss` over
`[Straight, Wavy, Curly, Black, Brown, Short, Medium, Long]`. For Krey that's **out of scope**:
- **Colour** (Black/Brown) is already read deterministically — don't relearn it.
- **Length** (Short/Med/Long) isn't in the §6 identity contract (it changes often, low
  identity value; it's an M2 style attribute at most).
- **Texture is one dominant class**, so it's a **single-label 4-way softmax + cross-entropy**
  (`straight / wavy / curly / coily`), not multi-label BCE. Softmax gives the `confidence`
  the slot needs directly.

Keep the same backbone (ResNet18 / EfficientNet, transfer-learned) — just a **4-logit head +
CrossEntropyLoss**, and `softmax` for the confidence. Reserve the multi-label BCE pattern for
a future M2 "style attributes" model if we ever want length/updo/etc.

```python
# texture head — single-label (fills the hair_texture slot)
backbone = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
backbone.fc = nn.Linear(backbone.fc.in_features, 4)   # straight, wavy, curly, coily
criterion = nn.CrossEntropyLoss()
# infer:  p = softmax(logits); value = CLASSES[p.argmax()]; confidence = p.max()
```

## Data
| Source | Use | Notes |
|---|---|---|
| [kavyasreeb/hair-type-dataset](https://www.kaggle.com/datasets/kavyasreeb/hair-type-dataset) | **train (with remap)** | classes Curly/Straight/Wavy/**Kinky**/**Dreadlocks**. Remap **Kinky→coily**, **drop Dreadlocks** (a style, not a texture). **Not Indian** → domain shift; confirm licence. |
| [IndicFairFace](https://github.com/aarishshahmohsin/IndicFairFace) | **label → Indian fine-tune/eval** | Indian faces, **no texture labels** — hand-label a slice to fine-tune and, above all, to *validate* the model doesn't collapse Indian wavy/curly. |
| FairFace (verifywise page) | **skip for hair** | race/age/gender only — **no hair attributes**. |
| alpha `/alpha` flags | **ground truth over time** | users flagging a wrong texture are labelled corrections — the cheapest Indian-real signal. |

**The gap:** no source here has **Indian** texture labels. Train on kavyasreeb (remapped),
then **fine-tune + validate on Indian hair** (labelled IndicFairFace slice + alpha flags)
before trusting it — same domain-shift discipline as skin.

## Scaffold (in the repo)
Built and ready to run when data + a dev are in hand (`train/`, torch is an optional dep kept
out of the main requirements so Service A stays GPU-free):
- `train/hair_texture.py` — ResNet18 → 4-class softmax (CrossEntropy), auto-remap
  (kinky→coily, drop styles), train/val split, per-class accuracy, checkpoint + metrics.
- `train/infer.py` — `read_hair_texture(image)` returns the slot `{value, available,
  confidence}`; degrades to `{"available": False}` without torch/model (today's behaviour).
- `train/README.md` — fetch → train → fairness-gate → wire-in steps.
- Torch-free parts (label remap, sample building, degrade path) are covered by
  `tests/test_hair_texture_train.py`.

## Integration + guardrails
1. Train the 4-class texture head; export a small model (keep it CPU-friendly — the rest of
   Service A is GPU-free; a ResNet18 head runs fine on CPU).
2. **Already wired (env-gated):** `app/face.assemble_face` calls `train.infer.read_hair_texture`
   on the hair region when `KREY_HAIR_TEXTURE_MODEL` is set, and the model read replaces the
   heuristic stub; unset (today) → no-op, deterministic stub, recognition renormalises. So
   enabling is just: train a model → set the env var. Recognition coverage then goes to 100%.
   (Single-photo `/twin/extract-face` path is wired; the multi-photo capture path can be wired
   the same way later.)
3. **Fairness gate before trust:** measure per-texture accuracy **on Indian hair specifically**
   (curly/coily are where biased models fail). Don't ship until Indian wavy/curly hold up.
4. Licence: confirm the training set's terms before commercial use (same rule as buffalo_l /
   SMPL-X, `docs/scope_bakeins.md`).

## Priority
This is **post-M1 polish**, not a launch blocker: the twin is recognisable at ~90% coverage
without texture. Do it when a dev + GPU are free (pairs naturally with Sohan's Step-2 GPU
setup, `docs/alpha_render_rollout.md`).
