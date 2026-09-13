"""Smoke test for the skin validation harness (synthetic images, PIL proxy — no cv2/network)."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bench.skin_report import run_report
from app.monk import MONK_SWATCHES


def _write_solid(path, rgb, size=64):
    from PIL import Image
    Image.new("RGB", (size, size), rgb).save(path)


def test_report_over_imagefolder_by_monk_bucket():
    # Build an ImageFolder-style set: subdirs "6" and "8" with solid swatch-coloured images.
    with tempfile.TemporaryDirectory() as d:
        for bucket in (6, 8):
            sub = os.path.join(d, str(bucket)); os.makedirs(sub)
            for i in range(3):
                _write_solid(os.path.join(sub, f"{i}.png"), MONK_SWATCHES[bucket])
        out = os.path.join(d, "reports")
        s = run_report(d, name="synthetic", out_dir=out, limit=None)

        assert s["n_images_read"] == 6
        assert "pil-proxy" in s["skin_extractor"]          # no cv2 in this env
        # solid swatch colours should classify to their own bucket → strong agreement
        assert s["labelled"]["n"] == 6
        assert s["labelled"]["exact_bucket_agreement"] >= 0.8
        # report files were written
        assert os.path.exists(os.path.join(out, "synthetic.json"))
        assert os.path.exists(os.path.join(out, "synthetic.md"))
        with open(os.path.join(out, "synthetic.json")) as f:
            assert json.load(f)["dataset"] == "synthetic"


def test_report_flat_folder_no_labels():
    with tempfile.TemporaryDirectory() as d:
        for i in range(2):
            _write_solid(os.path.join(d, f"img{i}.png"), MONK_SWATCHES[5])
        s = run_report(d, name="flat", out_dir=os.path.join(d, "r"))
        assert s["n_images_read"] == 2
        assert "labelled" not in s                          # no numeric subdirs → no agreement block


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
