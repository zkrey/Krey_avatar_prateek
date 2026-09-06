"""
Deterministic verification of the GPU-benchmark harness — aggregation math, warm/cold
split, subsidy-input mapping, the budget wall, and the offline dry-run. No network, no key,
no GPU, no spend.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from bench import bench_core
from bench.gpu_benchmark import (DryRunProvider, LocalProvider, _parse_latencies,
                                 preflight_budget, run_benchmark, main,
                                 resolve_model, build_input, MODEL_PRESETS)


# ---- model presets + input building (per-model schema, pure) --------------------------
def test_resolve_preset_shortname():
    spec = resolve_model("idm-vton")
    assert spec["ref"] == "cuuupid/idm-vton"
    assert spec["person_key"] == "human_img" and spec["garment_key"] == "garm_img"


def test_resolve_raw_ref_gets_default_keys():
    spec = resolve_model("someowner/some-model")
    assert spec["ref"] == "someowner/some-model"
    assert spec["person_key"] == "human_img"


def test_build_input_maps_person_and_garment():
    spec = resolve_model("idm-vton")
    payload = build_input(spec, "P.jpg", "G.jpg")
    assert payload["human_img"] == "P.jpg" and payload["garm_img"] == "G.jpg"
    assert payload["garment_des"] == "garment"        # preset extra carried through


def test_build_input_cli_overrides_win():
    spec = resolve_model("someowner/x")
    payload = build_input(spec, "P", "G", person_key="model_image", garment_key="cloth_image",
                          extra={"steps": 30})
    assert payload == {"model_image": "P", "cloth_image": "G", "steps": 30}


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


# ---- local provider (log a self-hosted render alongside the cloud number) -------------
def test_parse_latencies_comma_and_file(tmp_path):
    assert _parse_latencies("12.3,11.8, 11.9", None) == [12.3, 11.8, 11.9]
    f = tmp_path / "lat.txt"
    f.write_text("12.3\n11.8  # warm\n\n11.9\n")
    assert _parse_latencies(None, str(f)) == [12.3, 11.8, 11.9]


def test_parse_latencies_rejects_junk():
    with pytest.raises(SystemExit):
        _parse_latencies("12.3,notanumber", None)
    with pytest.raises(SystemExit):
        _parse_latencies(None, None)   # nothing provided


def test_local_provider_first_cold_gpu_equals_wallclock():
    p = LocalProvider(latencies=[20.0, 12.0, 11.5], gpu_frac=1.0)
    runs = run_benchmark(p, 3, None, None, "catvton-local")
    assert runs[0]["cold"] is True and all(r["cold"] is False for r in runs[1:])
    assert runs[1]["gpu_s"] == 12.0 and runs[1]["cost_usd"] is None   # dedicated card: GPU-s == wall-clock
    assert all(r["ok"] for r in runs)


def test_main_local_end_to_end_matches_cloud_shape():
    # warm-only measured renders -> the same summary/subsidy shape as a cloud run
    out = main(["--provider", "local", "--model", "catvton-local",
                "--latencies", "12.0,11.8,11.9", "--all-warm"])
    s = out["summary"]
    assert s["provider"] == "local" and s["n_ok"] == 3 and s["n_cold"] == 0
    # GPU-seconds per render is populated and cloud-equivalent cost derives from it
    assert s["subsidy_inputs"]["gpu_seconds_per_render"] is not None
    assert s["cost_per_render"]["inr_derived"] is not None
