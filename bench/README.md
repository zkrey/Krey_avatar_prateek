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

## The real benchmark — what you provision
1. **A GPU host account + key.** Recommended: **Replicate** (per-second billing, try-on
   models already hosted). Set the key in the environment — never in a file:
   ```bash
   export REPLICATE_API_TOKEN=...
   ```
2. **A person image + a garment image** (paths or URLs the model accepts).
3. **A spend cap.** `--budget-usd` is a hard wall — the harness estimates the run up front
   and *refuses to start* if it would exceed the cap. Start tiny.

```bash
python -m bench.gpu_benchmark --provider replicate \
    --model "cuuupid/idm-vton:<version-hash>" --runs 8 \
    --person person.jpg --garment garment.jpg \
    --budget-usd 2.00 --usd-per-gpu-s 0.001 --fx 85 \
    --out bench_idmvton.json
```

Run it once per candidate model (IDM-VTON, CatVTON, OOTDiffusion), then compare the
`bench_*.json` files — cheapest warm cost/render wins, latency breaks ties.

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
