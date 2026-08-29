"""
Deterministic verification of the GPU-benchmark harness — aggregation math, warm/cold
split, subsidy-input mapping, the budget wall, and the offline dry-run. No network, no key,
no GPU, no spend.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from bench import bench_core
from bench.gpu_benchmark import DryRunProvider, preflight_budget, run_benchmark, main


# ---- percentile core ------------------------------------------------------------------
def test_percentile_basic():
    assert bench_core.percentile([1, 2, 3, 4], 50) == 2.5
    assert bench_core.percentile([10], 90) == 10.0
    assert bench_core.percentile([], 50) is None


def test_percentile_ignores_none():
    assert bench_core.percentile([1, None, 3], 50) == 2.0


# ---- cost math ------------------------------------------------------------------------
def test_cost_per_render_inr():
    # 6 GPU-s × $0.001/s × ₹85 = ₹0.51
    assert bench_core.cost_per_render_inr(6.0, 0.001, 85.0) == 0.51


def test_cost_none_when_gpu_unreported():
    assert bench_core.cost_per_render_inr(None, 0.001, 85.0) is None


# ---- summarize: warm/cold split -------------------------------------------------------
def _runs():
    return [
        {"latency_s": 13.0, "gpu_s": 11.0, "cost_usd": 0.011, "ok": True, "cold": True},
        {"latency_s": 4.0, "gpu_s": 3.6, "cost_usd": 0.0036, "ok": True, "cold": False},
        {"latency_s": 4.4, "gpu_s": 3.9, "cost_usd": 0.0039, "ok": True, "cold": False},
        {"latency_s": 3.8, "gpu_s": 3.4, "cost_usd": 0.0034, "ok": True, "cold": False},
    ]


def test_summarize_splits_warm_and_cold():
    s = bench_core.summarize(_runs(), model="m", usd_per_gpu_s=0.001, fx=85.0)
    assert s["n_ok"] == 4 and s["n_cold"] == 1
    assert s["latency_s"]["cold"]["n"] == 1
    assert s["latency_s"]["warm"]["n"] == 3
    # cost/render uses the WARM gpu-seconds mean, not the cold-inflated one
    assert s["cost_per_render"]["gpu_seconds_used"] == s["gpu_seconds"]["warm"]["mean"]


def test_summarize_subsidy_inputs_map_to_sliders():
    s = bench_core.summarize(_runs(), model="m")
    si = s["subsidy_inputs"]
    assert si["gpu_seconds_per_render"] == pytest.approx(3.633, abs=0.01)  # warm mean
    # cold overhead = cold p50 latency (13) − warm p50 latency (4.0) = 9.0
    assert si["cold_start_overhead_s"] == pytest.approx(9.0, abs=0.01)


def test_summarize_flags_unreported_gpu():
    runs = [{"latency_s": 4.0, "gpu_s": None, "cost_usd": None, "ok": True, "cold": False}]
    s = bench_core.summarize(runs, model="m")
    assert "gpu_seconds_unreported" in s["notes"]
    assert s["cost_per_render"]["inr_derived"] is None


def test_summarize_all_failed():
    runs = [{"latency_s": 1.0, "gpu_s": None, "ok": False, "cold": False, "error": "boom"}]
    s = bench_core.summarize(runs, model="m")
    assert s["n_ok"] == 0 and "all_runs_failed" in s["notes"]


# ---- leaderboard ----------------------------------------------------------------------
def test_compare_ranks_cheapest_first():
    a = bench_core.summarize(_runs(), model="cheap", usd_per_gpu_s=0.0005)
    b = bench_core.summarize(_runs(), model="pricey", usd_per_gpu_s=0.002)
    board = bench_core.compare([b, a])
    assert board["cheapest"] == "cheap"
    assert board["ranked"][0]["model"] == "cheap"


# ---- the budget wall ------------------------------------------------------------------
def test_budget_refuses_over_cap():
    with pytest.raises(SystemExit):
        preflight_budget(n_runs=100, budget_usd=0.50)   # 100×$0.02=$2 > $0.50


def test_budget_allows_within_cap():
    preflight_budget(n_runs=5, budget_usd=1.00)         # 5×$0.02=$0.10 < $1 -> no raise


def test_budget_none_is_unbounded():
    preflight_budget(n_runs=10_000, budget_usd=None)    # dry runs have no cap -> no raise


# ---- dry-run offline (no key, no spend) -----------------------------------------------
def test_dry_provider_first_run_cold_rest_warm():
    p = DryRunProvider()
    runs = run_benchmark(p, 4, None, None, "dry/try-on")
    assert runs[0]["cold"] is True
    assert all(r["cold"] is False for r in runs[1:])
    assert all(r["ok"] for r in runs)


def test_main_dry_end_to_end():
    out = main(["--provider", "dry", "--runs", "5"])
    s = out["summary"]
    assert s["provider"] == "dry" and s["n_ok"] == 5
    assert s["subsidy_inputs"]["gpu_seconds_per_render"] is not None
    assert s["cost_per_render"]["inr_derived"] is not None
    assert out["leaderboard"]["cheapest"] == "dry/try-on"
