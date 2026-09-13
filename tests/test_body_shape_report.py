"""Smoke test for the tabular body-shape report (synthetic CSV, no cv2/network)."""
import sys, os, csv, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bench.body_shape_report import run_report


def _write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["chest", "waist", "hip", "shoulder", "sex", "height"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_report_over_measurement_csv():
    rows = [
        # female hourglass-ish (chest≈hip, deep waist drop)
        {"chest": 96, "waist": 68, "hip": 97, "shoulder": 38, "sex": 2, "height": 165},
        # female pear (hip > chest, waist drop on hip)
        {"chest": 88, "waist": 74, "hip": 104, "shoulder": 37, "sex": 2, "height": 160},
        # out-of-range waist (impossible) -> flagged
        {"chest": 95, "waist": 400, "hip": 98, "shoulder": 40, "sex": 2, "height": 168},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = os.path.join(d, "a.csv"); _write_csv(csv_path, rows)
        out = os.path.join(d, "reports")
        s = run_report(csv_path, name="synthetic_body", out_dir=out)

        assert s["n_rows"] == 3
        assert s["out_of_plausible_range"] >= 1            # the waist=400 row
        assert s["whr_mean"] is not None and s["whtr_mean"] is not None
        assert sum(s["shape_distribution"].values()) == 3
        assert os.path.exists(os.path.join(out, "synthetic_body.json"))
        with open(os.path.join(out, "synthetic_body.json")) as f:
            assert json.load(f)["dataset"] == "synthetic_body"


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
