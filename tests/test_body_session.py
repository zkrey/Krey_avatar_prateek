"""
Pure verification of the body-capture session: the measurability gate, recency-weighted +
outlier-robust measurement reconciliation, and the soft-confirm ladder. No pose model or
photo — synthetic per-frame measurements, like the face capture-core tests.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import measure_core as core
from app import body_session as bs


# ---- measurability gate ---------------------------------------------------------------
def _full_body(v=0.9):
    return {n: v for n in core.COCO_17}

def test_full_standing_body_is_measurable():
    out = core.body_measurable(_full_body())
    assert out["measurable"] is True and out["reason"] == "ok"


def test_headshot_is_not_measurable():
    vis = {n: 0.9 for n in ("nose", "left_eye", "right_eye", "left_shoulder", "right_shoulder")}
    out = core.body_measurable(vis)
    assert out["measurable"] is False and out["reason"] == "incomplete_body"


def test_waist_up_missing_legs_is_not_measurable():
    vis = _full_body()
    for leg in ("left_knee", "right_knee", "left_ankle", "right_ankle"):
        vis[leg] = 0.0
    assert core.body_measurable(vis)["measurable"] is False


# ---- reconciliation -------------------------------------------------------------------
def _frame(date, waist, conf=0.8):
    return {"date": date, "measurements": {"waist": {"circumference_cm": waist, "confidence": conf}}}

def test_recency_pulls_build_toward_the_fresh_frame():
    # three OLD frames at 80 cm, one FRESH frame at 92 cm -> current build leans fresh.
    frames = [_frame("2018-01-01", 80), _frame("2019-01-01", 80),
              _frame("2020-01-01", 80), _frame("2026-08-01", 92)]
    out = bs.reconcile_measurements(frames, mode="recent")
    stable = bs.reconcile_measurements(frames, mode="stable")
    assert out["waist"]["circumference_cm"] > stable["waist"]["circumference_cm"]


def test_reconcile_drops_a_measurement_outlier():
    frames = [_frame(f"202{i}-01-01", w) for i, w in enumerate([78, 79, 80, 81, 79])]
    frames.append(_frame("2026-01-01", 140))          # a bad-pose girth
    out = bs.reconcile_measurements(frames, mode="stable")
    assert out["waist"]["n_dropped_outliers"] >= 1
    assert out["waist"]["circumference_cm"] < 100      # outlier didn't drag it


def test_tight_agreement_is_high_confidence():
    frames = [_frame(f"2026-0{i}-01", 80) for i in (1, 2, 3, 4)]
    out = bs.reconcile_measurements(frames, mode="stable")
    assert out["waist"]["confidence"] >= 0.8 and out["waist"]["needs_confirm"] is False


def test_reconcile_empty_is_empty():
    assert bs.reconcile_measurements([]) == {}


# ---- identity-anchored pose selection -------------------------------------------------
def test_pose_inside_user_face_box_is_picked():
    # user's face box around (100,100); three poses' heads, one inside the box.
    heads = [(300, 300), (105, 102), (500, 90)]      # pose 1 is the user
    assert bs.select_pose_for_face(heads, (80, 80, 130, 140)) == 1


def test_nearest_head_within_reach_when_none_inside():
    heads = [(160, 110), (600, 600)]                 # none inside, pose 0 is close
    assert bs.select_pose_for_face(heads, (80, 80, 130, 140)) == 0


def test_no_pose_when_user_far_from_every_head():
    heads = [(900, 900), (950, 20)]                  # all far from the box
    assert bs.select_pose_for_face(heads, (80, 80, 130, 140)) is None


def test_no_face_box_no_selection():
    assert bs.select_pose_for_face([(100, 100)], None) is None
    assert bs.select_pose_for_face([], (0, 0, 10, 10)) is None


# ---- decision ladder ------------------------------------------------------------------
def test_body_decision_ladder():
    assert bs.body_capture_decision(0, 0.9) == "retake_no_body"
    assert bs.body_capture_decision(1, 0.4) == "reconfirm"
    assert bs.body_capture_decision(2, 0.9) == "reconfirm"
    assert bs.body_capture_decision(3, 0.7) == "accept"
    assert bs.body_capture_decision(4, 0.4) == "reconfirm"   # frames ok but confidence low


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
