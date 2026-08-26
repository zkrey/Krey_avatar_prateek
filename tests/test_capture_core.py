"""
Deterministic verification of the capture-session aggregation core — clustering, user
selection, identity confidence, the soft-confirm ladder, recency weighting, and the
recency-aware attribute fusion. Pure stdlib: synthetic embeddings/dates, no model.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app import capture_core as cc


# ---- timestamps (incl. the failure modes seen on real photos) -------------------------
def test_exif_date_parsed():
    assert cc.parse_capture_date("2026:08:26 22:57:47") == "2026-08-26"


def test_corrupted_exif_falls_back_to_filename():
    # a real case: EXIF was null bytes, filename carried the date.
    assert cc.parse_capture_date("\x00\x00\x00\x00", "PXL_20231226_060333645.jpg") == "2023-12-26"


def test_whatsapp_stripped_exif_uses_filename():
    assert cc.parse_capture_date(None, "IMG-20161102-WA0003.jpg") == "2016-11-02"


def test_no_readable_date_is_none_never_now():
    assert cc.parse_capture_date(None, "selfie.jpg") is None
    assert cc.parse_capture_date("garbage", "no-date-here.png") is None
    assert cc.parse_capture_date("2026:13:40 00:00:00", None) is None   # invalid month/day


# ---- identity clustering + user selection ---------------------------------------------
def _v(*xs):
    return list(xs)

def test_clusters_two_distinct_identities():
    # two tight groups far apart in space
    A = [_v(1, 0, 0), _v(0.98, 0.02, 0), _v(0.97, 0.0, 0.03)]
    B = [_v(0, 1, 0), _v(0.02, 0.98, 0)]
    labels = cc.cluster_by_similarity(A + B)
    assert labels[0] == labels[1] == labels[2]         # A together
    assert labels[3] == labels[4]                      # B together
    assert labels[0] != labels[3]                      # A != B


def test_user_is_the_identity_over_most_dates():
    # cluster 0 appears on 3 dates, cluster 1 on 1 date -> user = 0
    labels = [0, 0, 0, 1, 1]
    dates = ["2016-01-01", "2020-01-01", "2026-01-01", "2026-01-01", "2026-01-01"]
    assert cc.select_user_cluster(labels, dates) == 0


def test_select_user_none_when_empty():
    assert cc.select_user_cluster([], []) is None


# ---- identity confidence + soft-confirm ladder ----------------------------------------
def test_identity_confidence_high_for_tight_multiframe():
    out = cc.identity_confidence([0.7, 0.72, 0.68], n_frames=5, n_dates=4)
    assert out["overall"] >= 0.6 and out["surfaced_to_user"] is False


def test_identity_confidence_low_for_thin_evidence():
    out = cc.identity_confidence([0.4], n_frames=2, n_dates=1)
    assert out["overall"] < 0.6


def test_capture_decision_ladder():
    assert cc.capture_decision(0.8, 5) == "accept"
    assert cc.capture_decision(0.45, 3) == "reconfirm"      # one-tap, not re-upload
    assert cc.capture_decision(0.2, 2) == "retake_low_confidence"
    assert cc.capture_decision(0.9, 0) == "retake_no_face"


# ---- recency weighting ----------------------------------------------------------------
def test_recency_freshest_is_one_older_decays():
    w = cc.recency_weights(["2026-08-26", "2025-02-26", "2016-08-26"], half_life_days=540)
    assert w[0] == 1.0 and w[0] > w[1] > w[2]


def test_undated_frame_gets_baseline_not_anchor():
    w = cc.recency_weights(["2026-08-26", None])
    assert w[0] == 1.0 and w[1] == cc.UNDATED_WEIGHT


def test_all_undated_is_equal():
    assert cc.recency_weights([None, None, None]) == [1.0, 1.0, 1.0]


# ---- recency-aware attribute fusion ---------------------------------------------------
def test_stable_mode_is_confidence_weighted_vote():
    obs = [{"value": "dark_brown", "confidence": 0.9},
           {"value": "dark_brown", "confidence": 0.8},
           {"value": "hazel", "confidence": 0.4}]
    out = cc.aggregate_categorical(obs, mode="stable")
    assert out["value"] == "dark_brown" and out["agreement"] > 0.5


def test_recent_mode_lets_fresh_frame_override_stale_majority():
    # three OLD frames say "slim", one FRESH frame says "athletic".
    obs = [{"value": "slim", "confidence": 0.8},
           {"value": "slim", "confidence": 0.8},
           {"value": "slim", "confidence": 0.8},
           {"value": "athletic", "confidence": 0.85}]
    dates = ["2018-01-01", "2019-01-01", "2020-01-01", "2026-08-01"]
    recent = cc.aggregate_categorical(obs, mode="recent", dates=dates, half_life_days=365)
    stable = cc.aggregate_categorical(obs, mode="stable")
    assert stable["value"] == "slim"          # by raw count, old majority wins
    assert recent["value"] == "athletic"      # recency flips it to the current build


def test_numeric_fusion_is_a_weighted_mean_not_a_vote():
    # two people both bucket to Monk 6, but one's continuous tone sits darker.
    lighter = cc.aggregate_numeric([{"value": 5.7, "confidence": 0.8},
                                    {"value": 5.8, "confidence": 0.8},
                                    {"value": 5.9, "confidence": 0.8}])
    darker = cc.aggregate_numeric([{"value": 6.2, "confidence": 0.8},
                                   {"value": 6.4, "confidence": 0.8},
                                   {"value": 6.3, "confidence": 0.8}])
    assert lighter["display_bucket"] == darker["display_bucket"] == 6   # same label
    assert darker["value"] > lighter["value"]                          # different shade kept


def test_numeric_robust_rejects_a_lighting_outlier():
    # five consistent frames + one wild dark frame (the real failure mode).
    obs = [{"value": v, "confidence": 0.8} for v in (5.9, 6.0, 6.1, 6.0, 5.9)]
    obs.append({"value": 8.5, "confidence": 0.8})           # bad-lit outlier
    robust = cc.aggregate_numeric(obs, robust=True)
    plain = cc.aggregate_numeric(obs, robust=False)
    assert robust["n_dropped_outliers"] == 1 and plain["n_dropped_outliers"] == 0
    assert robust["value"] < plain["value"]                 # outlier no longer drags it
    assert robust["spread"] < plain["spread"]


def test_numeric_robust_keeps_genuine_spread():
    # a real range with no single outlier is preserved (not over-trimmed).
    obs = [{"value": v, "confidence": 0.8} for v in (5.6, 5.9, 6.2, 6.5, 6.8)]
    out = cc.aggregate_numeric(obs, robust=True)
    assert out["n_dropped_outliers"] == 0


def test_numeric_high_spread_flags_confirm():
    out = cc.aggregate_numeric([{"value": 5.0, "confidence": 0.7},
                                {"value": 7.5, "confidence": 0.7}])
    assert out["spread"] >= 2.0 and out["needs_confirm"] is True


def test_numeric_empty_is_none():
    assert cc.aggregate_numeric([]) is None


def test_aggregate_empty_is_none():
    assert cc.aggregate_categorical([]) is None
    assert cc.aggregate_categorical([{"value": None, "confidence": 0.9}]) is None


def test_recent_mode_requires_dates():
    with pytest.raises(ValueError):
        cc.aggregate_categorical([{"value": "x", "confidence": 0.5}], mode="recent")


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
