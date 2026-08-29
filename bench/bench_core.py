"""
GPU-benchmark aggregation core — pure stdlib, deterministic, no network, no keys.

The harness (bench/gpu_benchmark.py) runs a candidate try-on model N times and hands the
raw per-run measurements here. This module turns them into the numbers the Free-Tier
Subsidy model needs: GPU-seconds per render, latency percentiles, and cost per render in
$ and ₹. It is the tested heart (mirrors app/monk.py, app/measure_core.py) so the whole
cost math is verifiable without spending a rupee of GPU.

A "run" is one try-on render measured as a dict:
    {"latency_s": float, "gpu_s": float|None, "cost_usd": float|None, "ok": bool,
     "error": str|None, "cold": bool}
`gpu_s` / `cost_usd` are None when a provider doesn't report them; the summary carries
whichever it has and says which are missing, rather than inventing a number.
"""
from __future__ import annotations
from typing import Optional


def percentile(values: list, p: float) -> Optional[float]:
    """Linear-interpolated percentile (p in 0..100). None for empty input."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return float(xs[0])
    rank = (p / 100.0) * (len(xs) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(xs) - 1)
    frac = rank - lo
    return float(xs[lo] + (xs[hi] - xs[lo]) * frac)


def _stat_block(values: list) -> Optional[dict]:
    xs = [v for v in values if v is not None]
    if not xs:
        return None
    return {
        "n": len(xs),
        "mean": round(sum(xs) / len(xs), 4),
        "p50": round(percentile(xs, 50), 4),
        "p90": round(percentile(xs, 90), 4),
        "p95": round(percentile(xs, 95), 4),
        "min": round(min(xs), 4),
        "max": round(max(xs), 4),
    }


def cost_per_render_inr(gpu_s: Optional[float], usd_per_gpu_s: float, fx: float) -> Optional[float]:
    """₹ for one render from measured GPU-seconds. None if GPU-seconds weren't reported."""
    if gpu_s is None:
        return None
    return round(gpu_s * usd_per_gpu_s * fx, 4)


def summarize(runs: list, *, model: str, usd_per_gpu_s: float = 0.001, fx: float = 85.0,
              provider: str = "unknown") -> dict:
    """
    Fold raw per-run measurements into one model's benchmark summary.

    Separates WARM from COLD runs (a cold-start's boot seconds are billed too, so they
    belong to the free/standard lane's cost, not the priority lane's). Reports latency and
    GPU-second blocks for each, plus derived cost/render. Never invents a missing number —
    a None GPU-second field yields a null cost and a "gpu_seconds_unreported" note.
    """
    ok = [r for r in runs if r.get("ok")]
    failed = [r for r in runs if not r.get("ok")]
    warm = [r for r in ok if not r.get("cold")]
    cold = [r for r in ok if r.get("cold")]

    lat_warm = _stat_block([r.get("latency_s") for r in warm])
    lat_cold = _stat_block([r.get("latency_s") for r in cold])
    gpu_warm = _stat_block([r.get("gpu_s") for r in warm])
    gpu_all = _stat_block([r.get("gpu_s") for r in ok])

    notes = []
    if not ok:
        notes.append("all_runs_failed")
    if gpu_all is None and ok:
        notes.append("gpu_seconds_unreported")   # provider gave no GPU-second metric
    if failed:
        notes.append(f"{len(failed)}_failed")

    # Cost/render uses WARM GPU-seconds (the steady-state lane); falls back to all-runs mean.
    gpu_for_cost = (gpu_warm or gpu_all or {}).get("mean")
    cost_warm_inr = cost_per_render_inr(gpu_for_cost, usd_per_gpu_s, fx)
    # Reported cost, if the provider bills directly (authoritative over the derived figure).
    reported = _stat_block([r.get("cost_usd") for r in ok])

    return {
        "model": model,
        "provider": provider,
        "n_runs": len(runs),
        "n_ok": len(ok),
        "n_failed": len(failed),
        "n_cold": len(cold),
        "latency_s": {"warm": lat_warm, "cold": lat_cold},
        "gpu_seconds": {"warm": gpu_warm, "all": gpu_all},
        "cost_per_render": {
            "gpu_seconds_used": gpu_for_cost,
            "usd_per_gpu_s": usd_per_gpu_s,
            "fx_inr": fx,
            "inr_derived": cost_warm_inr,
            "usd_reported_mean": (reported or {}).get("mean"),
        },
        "subsidy_inputs": subsidy_inputs(gpu_warm, gpu_all, lat_warm, lat_cold),
        "notes": notes,
    }


def subsidy_inputs(gpu_warm, gpu_all, lat_warm, lat_cold) -> dict:
    """The exact fields the Free-Tier Subsidy model's 'assumed' sliders want, so the
    measured numbers drop straight in. Cold overhead = cold p50 latency − warm p50."""
    warm_gpu = (gpu_warm or gpu_all or {}).get("mean")
    cold_over = None
    if lat_warm and lat_cold:
        cold_over = round(max(0.0, lat_cold["p50"] - lat_warm["p50"]), 2)
    return {
        "gpu_seconds_per_render": warm_gpu,      # -> "GPU-seconds / render" slider
        "cold_start_overhead_s": cold_over,      # -> "Cold-start overhead (free lane)"
        "warm_latency_p50_s": (lat_warm or {}).get("p50"),
        "warm_latency_p90_s": (lat_warm or {}).get("p90"),
    }


def compare(summaries: list) -> dict:
    """Rank models by warm cost/render (cheapest first); ties broken by warm p90 latency.
    Models missing a cost figure sort last. Returns a compact leaderboard."""
    def key(s):
        c = s["cost_per_render"]["inr_derived"]
        lat = (s["latency_s"]["warm"] or {}).get("p90")
        return (c is None, c if c is not None else 0.0, lat if lat is not None else 0.0)
    ranked = sorted(summaries, key=key)
    return {
        "ranked": [
            {"model": s["model"], "cost_inr": s["cost_per_render"]["inr_derived"],
             "gpu_s": s["subsidy_inputs"]["gpu_seconds_per_render"],
             "warm_p50_s": s["subsidy_inputs"]["warm_latency_p50_s"],
             "warm_p90_s": s["subsidy_inputs"]["warm_latency_p90_s"],
             "notes": s["notes"]}
            for s in ranked
        ],
        "cheapest": ranked[0]["model"] if ranked else None,
    }
