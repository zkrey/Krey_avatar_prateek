"""
Subprocess entry point for ONE isolated body-frame measurement.

Run as: python -m app._pose_worker  (reads a JSON payload on stdin, writes the row on
stdout). Isolated on purpose: MediaPipe's pose segmentation occasionally aborts natively
(SIGABRT) on a bad frame, which no in-process try/except can catch. Running the measure
here means such an abort kills only this child; the parent (body_session._run_pose_worker)
sees the non-zero exit and skips that one frame. Model-heavy imports stay inside the call.
"""
import sys
import json


def main() -> None:
    payload = json.load(sys.stdin)
    from app.body_session import _measure_one
    row = _measure_one(payload["path"], payload["height"], payload["weight"], payload["sex"],
                       payload.get("body_type"), payload.get("model_path"),
                       payload.get("user_reference"))
    if row is None:
        row = {"photo": "", "date": None, "measurable": False,
               "reason": "unreadable", "coverage": 0.0}
    sys.stdout.write(json.dumps(row))


if __name__ == "__main__":
    main()
