"""
GPU try-on benchmark harness — the tool that turns the Free-Tier Subsidy model's biggest
"assumed" slider (GPU-seconds per render) into a measured number.

It runs a candidate try-on diffusion model N times against a person+garment pair, measures
wall-clock latency and (where the provider reports it) GPU-seconds and cost, then hands the
runs to bench_core for aggregation and a leaderboard. The output JSON's `subsidy_inputs`
drop straight into the subsidy artifact.

FRUGALITY + SAFETY (the money guardrail):
  - Providers that spend real money need an API KEY from the environment; none is stored.
  - `--budget-usd` is a hard cap: the harness estimates the run's cost up front and REFUSES
    to start if the projection exceeds the cap. It never silently overspends.
  - `--provider dry` runs fully offline with synthetic-but-deterministic numbers, so you can
    see the exact output shape (and the tests can verify the math) without a key or a rupee.

Usage:
    # offline shape check — free, no key:
    python -m bench.gpu_benchmark --provider dry --runs 6

    # real benchmark (after you provision the key + accept the spend):
    export REPLICATE_API_TOKEN=...          # or FAL_KEY for --provider fal
    python -m bench.gpu_benchmark --provider replicate \\
        --model "cuuupid/idm-vton:<version>" --runs 8 \\
        --person person.jpg --garment garment.jpg \\
        --budget-usd 2.00 --out bench_result.json
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from typing import Optional

from bench import bench_core

# Rough per-run cost estimate ($) used ONLY for the pre-flight budget check. Deliberately
# conservative (assume a cold-ish A100 render) so the guard errs toward stopping early.
_EST_USD_PER_RUN = 0.02


# --------------------------------------------------------------------------------------
# Candidate try-on models. Each maps the person/garment pair onto that model's own input
# field names (they differ per model) + any required extra fields. Pass a shortname to
# --model and the harness fills the ref + schema; or pass a full "owner/model[:version]"
# and override the keys with --person-key/--garment-key. ALWAYS verify a model's exact
# fields on its Replicate "API" tab — schemas change. Only idm-vton is pre-filled from a
# known-good schema; the others are templates to confirm before a paid run.
MODEL_PRESETS = {
    "idm-vton": {"ref": "cuuupid/idm-vton",
                 "person_key": "human_img", "garment_key": "garm_img",
                 "extra": {"garment_des": "garment"}},
    # Templates — confirm ref + keys on the model page, then uncomment / adjust:
    # "oot":     {"ref": "<owner>/oot_diffusion", "person_key": "model_image",
    #             "garment_key": "garment_image", "extra": {}},
    # "catvton": {"ref": "<owner>/catvton", "person_key": "person_image",
    #             "garment_key": "cloth_image", "extra": {}},
}


def resolve_model(model: str) -> dict:
    """Turn a --model value into {ref, person_key, garment_key, extra}. Accepts a preset
    shortname (idm-vton) or a raw 'owner/model[:version]' ref (uses default try-on keys,
    override with --person-key/--garment-key). Pure — no network."""
    if model in MODEL_PRESETS:
        return dict(MODEL_PRESETS[model])
    return {"ref": model, "person_key": "human_img", "garment_key": "garm_img", "extra": {}}


def build_input(spec: dict, person, garment, person_key=None, garment_key=None,
                extra: Optional[dict] = None) -> dict:
    """Assemble the model's input dict from the person + garment images and the model's
    field names. CLI overrides win over the preset. Pure — the tested seam that keeps the
    per-model schema out of the network path."""
    pk = person_key or spec["person_key"]
    gk = garment_key or spec["garment_key"]
    payload = {pk: person, gk: garment}
    payload.update(spec.get("extra") or {})
    payload.update(extra or {})
    return payload


# --------------------------------------------------------------------------------------
# Providers — each returns one run dict; injected so the core stays testable & keyless.
# --------------------------------------------------------------------------------------
class DryRunProvider:
    """Synthetic, deterministic renders. No network, no key, no spend — for shape + tests.
    First run is 'cold' (slow), the rest 'warm', mimicking a scale-to-zero GPU."""
    name = "dry"

    def __init__(self, warm_s=4.0, cold_extra_s=9.0, gpu_frac=0.9, usd_per_gpu_s=0.001):
        self.warm_s, self.cold_extra_s = warm_s, cold_extra_s
        self.gpu_frac, self.usd_per_gpu_s = gpu_frac, usd_per_gpu_s

    def run(self, i, person, garment, model):
        cold = (i == 0)
        latency = self.warm_s + (self.cold_extra_s if cold else 0.0)
        gpu_s = round(latency * self.gpu_frac, 3)
        return {"latency_s": round(latency, 3), "gpu_s": gpu_s,
                "cost_usd": round(gpu_s * self.usd_per_gpu_s, 5),
                "ok": True, "error": None, "cold": cold}


class ReplicateProvider:
    """Runs a model on Replicate; reads REPLICATE_API_TOKEN. Lazy-imports the client so the
    harness (and tests) load without the dep. GPU-seconds/cost come from prediction metrics
    where Replicate reports them (`predict_time`), else None (core marks it unreported)."""
    name = "replicate"

    def __init__(self, usd_per_gpu_s=0.001, person_key=None, garment_key=None, extra=None):
        self.usd_per_gpu_s = usd_per_gpu_s
        self.person_key, self.garment_key, self.extra = person_key, garment_key, extra
        self.token = os.environ.get("REPLICATE_API_TOKEN")
        if not self.token:
            raise RuntimeError("REPLICATE_API_TOKEN not set — provision the key before a paid run")

    def _version(self, client, ref):
        """Resolve 'owner/model[:version]' to a version id. If no version is pinned, ask the
        API for the latest — so you never hand-copy a version hash."""
        if ":" in ref:
            return ref.split(":")[-1]
        owner_model = ref
        m = client.models.get(owner_model)
        return m.latest_version.id

    def run(self, i, person, garment, model):
        import replicate  # lazy
        spec = resolve_model(model)
        payload = build_input(spec, person, garment, self.person_key, self.garment_key, self.extra)
        t0 = time.time()
        try:
            client = replicate.Client(api_token=self.token)
            pred = client.predictions.create(version=self._version(client, spec["ref"]),
                                              input=payload)
            pred.wait()
            latency = time.time() - t0
            metrics = getattr(pred, "metrics", None) or {}
            gpu_s = metrics.get("predict_time")
            return {"latency_s": round(latency, 3),
                    "gpu_s": round(gpu_s, 3) if gpu_s is not None else None,
                    "cost_usd": round(gpu_s * self.usd_per_gpu_s, 5) if gpu_s is not None else None,
                    "ok": pred.status == "succeeded", "error": None if pred.status == "succeeded" else pred.status,
                    "cold": i == 0}
        except Exception as e:  # a failed render is data, not a crash — record and continue
            return {"latency_s": round(time.time() - t0, 3), "gpu_s": None, "cost_usd": None,
                    "ok": False, "error": f"{type(e).__name__}: {e}", "cold": i == 0}


PROVIDERS = {"dry": DryRunProvider, "replicate": ReplicateProvider}


def preflight_budget(n_runs: int, budget_usd) -> None:
    """Refuse to start a paid run whose worst-case estimate exceeds the cap. The money wall."""
    if budget_usd is None:
        return
    projected = n_runs * _EST_USD_PER_RUN
    if projected > budget_usd:
        raise SystemExit(
            f"REFUSING: estimated ${projected:.2f} for {n_runs} runs exceeds "
            f"--budget-usd ${budget_usd:.2f}. Lower --runs or raise the cap.")


def run_benchmark(provider, n_runs, person, garment, model) -> list:
    runs = []
    for i in range(n_runs):
        r = provider.run(i, person, garment, model)
        runs.append(r)
        tag = "cold" if r["cold"] else "warm"
        print(f"  run {i+1}/{n_runs} [{tag}] {r['latency_s']}s "
              f"gpu={r['gpu_s']}s ok={r['ok']}", file=sys.stderr)
    return runs


def main(argv=None):
    ap = argparse.ArgumentParser(description="Krey try-on GPU benchmark")
    ap.add_argument("--provider", default="dry", choices=list(PROVIDERS))
    ap.add_argument("--model", default="dry/try-on")
    ap.add_argument("--runs", type=int, default=6)
    ap.add_argument("--person", default=None, help="person image (path/URL) — provider-specific")
    ap.add_argument("--garment", default=None, help="garment image (path/URL)")
    ap.add_argument("--budget-usd", type=float, default=None, help="hard spend cap (paid providers)")
    ap.add_argument("--usd-per-gpu-s", type=float, default=0.001)
    ap.add_argument("--fx", type=float, default=85.0, help="USD->INR")
    ap.add_argument("--person-key", default=None, help="override the model's person-image field name")
    ap.add_argument("--garment-key", default=None, help="override the model's garment-image field name")
    ap.add_argument("--extra-input", default=None, help="JSON merged into the model input (model-specific fields)")
    ap.add_argument("--out", default=None, help="write full JSON summary here")
    args = ap.parse_args(argv)

    extra = json.loads(args.extra_input) if args.extra_input else None

    if args.provider != "dry":
        preflight_budget(args.runs, args.budget_usd)
        if not args.person or not args.garment:
            raise SystemExit("a paid provider needs --person and --garment images")

    provider = PROVIDERS[args.provider](usd_per_gpu_s=args.usd_per_gpu_s) if args.provider == "dry" \
        else PROVIDERS[args.provider](usd_per_gpu_s=args.usd_per_gpu_s, person_key=args.person_key,
                                      garment_key=args.garment_key, extra=extra)
    print(f"Benchmarking '{args.model}' via {provider.name} — {args.runs} runs", file=sys.stderr)
    runs = run_benchmark(provider, args.runs, args.person, args.garment, args.model)

    summary = bench_core.summarize(runs, model=args.model, usd_per_gpu_s=args.usd_per_gpu_s,
                                   fx=args.fx, provider=provider.name)
    board = bench_core.compare([summary])

    out = {"summary": summary, "leaderboard": board}
    print(json.dumps(out, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\nwrote {args.out}", file=sys.stderr)

    si = summary["subsidy_inputs"]
    print("\n── drop these into the Free-Tier Subsidy model ──", file=sys.stderr)
    print(f"  GPU-seconds / render : {si['gpu_seconds_per_render']}", file=sys.stderr)
    print(f"  cold-start overhead  : {si['cold_start_overhead_s']} s", file=sys.stderr)
    print(f"  warm latency p50/p90 : {si['warm_latency_p50_s']}/{si['warm_latency_p90_s']} s", file=sys.stderr)
    print(f"  cost / render        : ₹{summary['cost_per_render']['inr_derived']}", file=sys.stderr)
    return out


if __name__ == "__main__":
    main()
