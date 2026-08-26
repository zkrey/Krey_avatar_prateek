"""
Deterministic verification of the analytics event layer. No network, no warehouse —
events go to an in-memory sink.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
import pytest
from app.analytics import Analytics, Spine, MemorySink, SCHEMA_VERSION, M2_EVENTS
from app.eligibility import can_render, M1_JURISDICTION
from app import monk


def spine(**over):
    base = dict(session_id="s1", surface="onboarding", app_version="1.0.0",
                device_os="android-14", signed_in=True, user_id="u1",
                entry_point="tap", region="IN")
    base.update(over)
    return Spine(**base)


def test_spine_requires_a_user_or_guest_id():
    with pytest.raises(ValueError):
        Spine(session_id="s", surface="x", app_version="1", device_os="a",
              signed_in=False).validate()   # neither id
    spine(user_id=None, guest_id="g1").validate()   # guest-only is fine


def test_spine_rejects_unknown_entry_point():
    with pytest.raises(ValueError):
        spine(entry_point="telepathy").validate()


def test_every_event_carries_spine_and_envelope():
    sink = MemorySink(); a = Analytics(sink)
    rec = a.avatar_build(spine(), status="done", duration_s=12.3)
    assert rec["schema_version"] == SCHEMA_VERSION and rec["event"] == "avatar_build"
    assert rec["session_id"] == "s1" and rec["surface"] == "onboarding"
    assert rec["region"] == "IN" and rec["signed_in"] is True and "ts" in rec
    assert rec["props"]["status"] == "done" and rec["props"]["duration_s"] == 12.3
    assert sink.events == [rec]


def test_twin_extracted_from_a_real_monk_reading():
    sink = MemorySink(); a = Analytics(sink)
    mt = monk.classify([(160, 126, 86), (159, 125, 87), (161, 127, 85)])   # ~MST6
    a.twin_extracted(spine(), slice="skin", model=mt["model"],
                     confidence=mt["confidence"], needs_confirm=mt["needs_confirm"])
    e = sink.events[0]
    assert e["event"] == "twin_extracted" and e["props"]["slice"] == "skin"
    assert e["props"]["model"] == "deterministic-lab-mst-v0"


def test_eligibility_event_from_can_render_verdict():
    sink = MemorySink(); a = Analytics(sink)
    v = can_render(True, True, date(2000, 1, 1), date(2026, 8, 25),
                   token_balance=100, render_cost=10,
                   jurisdiction=M1_JURISDICTION, input_eligibility_passed=True)
    a.eligibility(spine(), allowed=v.allowed, reason=v.reason)
    assert sink.events[0]["props"] == {"allowed": True, "reason": "ok"}


def test_render_completed_must_carry_gpu_seconds():
    a = Analytics(MemorySink())
    with pytest.raises(ValueError):
        a.render(spine(), phase="completed", entry_point="styleme")   # no gpu_seconds
    rec = a.render(spine(), phase="completed", entry_point="styleme", gpu_seconds=6.2)
    assert rec["props"]["gpu_seconds"] == 6.2 and rec["props"]["entry_point"] == "styleme"


def test_render_rejects_unknown_entry_point():
    a = Analytics(MemorySink())
    with pytest.raises(ValueError):
        a.render(spine(), phase="requested", entry_point="bogus")


def test_guest_events_stitch_onto_user_at_signup():
    sink = MemorySink(); a = Analytics(sink)
    g = spine(user_id=None, guest_id="g9", signed_in=False)
    a.avatar_build(g, status="start")                       # pre-account, guest_id only
    a.stitch_identity(spine(), from_guest_id="g9", to_user_id="u1")
    assert sink.events[0]["guest_id"] == "g9" and sink.events[0]["user_id"] is None
    assert sink.events[1]["event"] == "identity_stitch"
    assert sink.events[1]["props"] == {"from_guest_id": "g9", "to_user_id": "u1"}


def test_social_events_have_schema_now_but_only_fire_in_m2():
    m1 = Analytics(MemorySink())                            # allow_m2 defaults False
    assert m1.track("tried_on", spine(), inspo_post_id="p1", creator="c1") is None
    assert m1.sink.events == []
    m2 = Analytics(MemorySink(), allow_m2=True)
    assert m2.track("tried_on", spine(), inspo_post_id="p1", creator="c1") is not None
    assert "tried_on" in M2_EVENTS                          # schema defined today


def test_missing_required_prop_raises():
    a = Analytics(MemorySink())
    with pytest.raises(ValueError):
        a.track("twin_extracted", spine(), slice="skin")   # missing 'model'


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
