# GPU benchmark — turning the Free-Tier Subsidy's guess into a number

This harness measures the one figure the subsidy model can only *assume*: **GPU-seconds per
render** (and, with it, cold-start overhead, warm latency, and cost per render). Its output
drops straight into the [Free-Tier Subsidy model](../docs/DEPLOY.md)'s sliders.

Nothing here spends money until **you** provision a GPU account + key and accept the cost.
Until then, the dry-run shows the exact shape for free.

## Try it now — free, offline
```bash
python -m bench.gpu_benchmark --provider dry --runs 6
```
No key, no network, no spend. First run is "cold" (slow), the rest "warm" — mimicking a
scale-to-zero GPU. You'll see the `subsidy_inputs` block the real run also produces.

## The real benchmark — the run sheet

**You provide three things; the harness handles the rest (no version-hash hunting).**

1. **A Replicate account + key** (per-second billing, try-on models hosted). Set it in the
   environment — never in a file:
   ```bash
   export REPLICATE_API_TOKEN=...
   pip install replicate            # only this offline tool needs it; the API service never does
   ```
2. **A person image + a garment image** — public URLs are simplest (the model fetches them).
3. **A spend cap** — `--budget-usd` is a hard wall: the harness estimates the run up front
   and *refuses to start* if it would exceed the cap. Start at $1–2.

**Run — one command, first candidate (IDM-VTON is pre-filled):**
```bash
python -m bench.gpu_benchmark --provider replicate --model idm-vton --runs 8 \
    --person https://…/person.jpg --garment https://…/garment.jpg \
    --budget-usd 2.00 --usd-per-gpu-s 0.001 --fx 85 --out bench_idmvton.json
```
- `--model idm-vton` resolves the ref + input field names for you; no version hash needed
  (the harness asks Replicate for the latest version at run time).
- First run is billed as "cold", the rest "warm" — that's the cold-start overhead measured.

**Adding the other candidates (CatVTON, OOTDiffusion):** open the model's **API** tab on
Replicate to see its input field names, then either add a preset in `MODEL_PRESETS`
(`bench/gpu_benchmark.py`) or pass a raw ref + key overrides on the CLI:
```bash
python -m bench.gpu_benchmark --provider replicate \
    --model "owner/oot-diffusion" \
    --person-key model_image --garment-key garment_image \
    --extra-input '{"steps":30}' \
    --runs 8 --person … --garment … --budget-usd 2.00 --out bench_oot.json
```

Run once per candidate, then compare the `bench_*.json` files — cheapest warm cost/render
wins, warm p90 latency breaks ties. `python -m bench.gpu_benchmark` prints a leaderboard
per file; the numbers you carry over are in each file's `summary.subsidy_inputs`.

## What you get
For each model: warm vs cold latency percentiles, GPU-seconds, and cost/render in ₹, plus:
```
── drop these into the Free-Tier Subsidy model ──
  GPU-seconds / render : <measured>
  cold-start overhead  : <measured> s
  warm latency p50/p90 : <measured>/<measured> s
  cost / render        : ₹<measured>
```
Move those four numbers onto the subsidy sliders and the biggest **assumed** tag turns
**measured** — and the ₹/converted-user figure becomes real.

## Cost of the benchmark itself
A few dollars total: ~8 renders × ~$0.01–0.03 each × 2–3 models. The `--budget-usd` cap
keeps it bounded; a first pass at `--runs 8` per model is plenty to get stable percentiles.

## Notes
- `--provider replicate` lazy-imports the `replicate` client (add `replicate` to your env
  before a paid run; it's intentionally NOT in `requirements.txt` — the API service never
  needs it, only this offline tool does).
- GPU-seconds come from the provider's own metric (Replicate's `predict_time`). If a
  provider doesn't report it, the summary says `gpu_seconds_unreported` rather than inventing
  a number, and cost/render is null until you supply a measured GPU-second figure.
- A failed render is recorded as data (`ok:false`) and the batch continues — one bad render
  never aborts the run.
