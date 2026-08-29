"""
Deterministic verification of the entitlements gate — the subscription play-loop wall.
Same features for every plan; plans differ only on quota + speed lane. The wow-inflection
upsell fires only after the magic has landed and only at the wall. No GPU, no clock, no I/O.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from app import entitlements as ent
from app.analytics import MemorySink
from app.main import app, analytics

client = TestClient(app)


# ---- plan resolution ------------------------------------------------------------------
def test_unknown_plan_defaults_to_free():
    p = ent.get_plan("enterprise-galaxy")
    assert p["plan"] == "free"
    assert p["daily_render_quota"] == ent.PLANS["free"]["daily_render_quota"]


def test_missing_plan_defaults_to_free():
    assert ent.get_plan(None)["plan"] == "free"


def test_plan_is_case_insensitive():
    assert ent.get_plan("PLUS")["label"] == "Plus"


# ---- same features, different quota/speed ---------------------------------------------
def test_paid_lifts_quota_not_features():
    # There are no feature flags to compare — every plan row carries only quota + lane.
    for pid in ent.PLANS:
        row = ent.PLANS[pid]
        assert set(row.keys()) == {"label", "daily_render_quota", "lane"}


def test_free_is_standard_lane_paid_is_priority():
    assert ent.render_lane("free") == "standard"
    assert ent.render_lane("plus") == "priority"
    assert ent.render_lane("pro") == "priority"


# ---- quota ----------------------------------------------------------------------------
def test_remaining_counts_down():
    assert ent.remaining("free", 0) == ent.PLANS["free"]["daily_render_quota"]
    assert ent.remaining("free", 2) == ent.PLANS["free"]["daily_render_quota"] - 2


def test_remaining_never_negative():
    assert ent.remaining("free", 9999) == 0


def test_pro_is_unlimited():
    assert ent.is_unlimited("pro") is True
    assert ent.remaining("pro", 10_000) is None


# ---- authorize ------------------------------------------------------------------------
def test_authorize_allows_within_quota():
    a = ent.authorize("free", used_today=0)
    assert a["allowed"] is True
    assert a["lane"] == "standard"
    assert a["renders_left"] == ent.PLANS["free"]["daily_render_quota"]


def test_authorize_blocks_at_quota():
    a = ent.authorize("free", used_today=ent.PLANS["free"]["daily_render_quota"])
    assert a["allowed"] is False
    assert a["reason"] == "daily_quota_reached"
    assert a["renders_left"] == 0


def test_authorize_unlimited_always_allowed():
    a = ent.authorize("pro", used_today=1_000_000)
    assert a["allowed"] is True
    assert a["unlimited"] is True
    assert a["renders_left"] is None


# ---- the wow-inflection upsell (the conversion doctrine) ------------------------------
def test_no_upsell_before_wow():
    # A user who has barely played must NOT be nagged — let the magic land first.
    s = ent.authorize("free", used_today=1)["upsell"]
    assert s["show"] is False
    assert s["reason"] == "pre_wow"


def test_upsell_fires_at_the_wall_after_wow():
    q = ent.PLANS["free"]["daily_render_quota"]
    s = ent.authorize("free", used_today=q)["upsell"]        # wow reached, quota spent
    assert s["show"] is True
    assert s["reason"] == "wow_inflection"
    assert s["moment"] == "at_wall"


def test_upsell_fires_approaching_the_wall():
    q = ent.PLANS["free"]["daily_render_quota"]
    s = ent.authorize("free", used_today=q - 1)["upsell"]    # one render left, post-wow
    assert s["show"] is True
    assert s["moment"] == "approaching_wall"
    assert s["renders_left"] == 1


def test_no_upsell_mid_quota():
    # Post-wow but with plenty left -> don't interrupt the flow.
    s = ent.authorize("plus", used_today=ent.WOW_THRESHOLD)["upsell"]
    assert s["show"] is False
    assert s["reason"] == "mid_quota"


def test_unlimited_never_upsells():
    s = ent.authorize("pro", used_today=1_000)["upsell"]
    assert s["show"] is False
    assert s["reason"] == "unlimited_plan"


# ---- The Habit Line (docs/DOCTRINE.md) ------------------------------------------------
def test_habit_core_is_always_free():
    # The invariant: nothing that builds the habit can ever resolve to paid — whatever the
    # conversion pressure. This is the guard that lives in code, not just prose.
    for feat in ent._HABIT_CORE:
        c = ent.classify_feature(feat)
        assert c["paid"] is False
        assert c["tier"] == ent.FREE_HABIT
        assert ent.is_free_habit(feat) is True


def test_fit_answer_and_try_on_never_paid():
    # The two load-bearing habit-builders, named explicitly so a future edit can't quietly
    # move them behind the wall without turning this red.
    assert ent.is_free_habit("fit_answer") is True
    assert ent.is_free_habit("try_on") is True


def test_leverage_is_paid():
    for feat in ent._PAID_LEVERAGE:
        c = ent.classify_feature(feat)
        assert c["paid"] is True and c["tier"] == ent.PAID_LEVERAGE


def test_new_value_is_paid():
    for feat in ent._PAID_NEW_VALUE:
        c = ent.classify_feature(feat)
        assert c["paid"] is True and c["tier"] == ent.PAID_NEW_VALUE


def test_unknown_feature_defaults_free():
    # "When in doubt, free" — mis-charging for a habit-builder is the costly error.
    c = ent.classify_feature("some_future_thing")
    assert c["paid"] is False and c["tier"] == ent.FREE_HABIT


# ---- endpoint wiring ------------------------------------------------------------------
def test_endpoint_authorizes_and_reports_lane():
    r = client.post("/render/authorize", json={"plan": "free", "used_today": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] is True and body["lane"] == "standard"


def test_endpoint_blocks_at_wall_with_upsell():
    q = ent.PLANS["free"]["daily_render_quota"]
    r = client.post("/render/authorize", json={"plan": "free", "used_today": q})
    body = r.json()
    assert body["allowed"] is False
    assert body["upsell"]["show"] is True


def test_endpoint_emits_render_requested_on_valid_entry_point():
    sink = MemorySink()
    analytics.sink = sink
    client.post("/render/authorize",
                json={"plan": "plus", "used_today": 0, "entry_point": "styleme", "user_id": "u-1"})
    reqs = [e for e in sink.events if e["event"] == "render" and e["props"]["phase"] == "requested"]
    assert len(reqs) == 1
    assert reqs[0]["props"]["entry_point"] == "styleme"
    assert reqs[0]["props"]["source"] == "priority"     # the plan's lane rides along


def test_endpoint_skips_analytics_on_bad_entry_point():
    sink = MemorySink()
    analytics.sink = sink
    # An unknown entry_point must not crash the gate (it just skips the funnel event).
    r = client.post("/render/authorize",
                    json={"plan": "free", "used_today": 0, "entry_point": "not-a-surface"})
    assert r.status_code == 200
    assert not any(e["event"] == "render" for e in sink.events)
