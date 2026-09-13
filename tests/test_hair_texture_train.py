"""Torch-free tests for the hair-texture scaffold: label remap, sample building, degrade path."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from train.hair_texture import remap_label, build_samples, CLASSES, CLASS_INDEX
from train.infer import read_hair_texture


def test_remap_label():
    assert remap_label("Straight") == "straight"
    assert remap_label("kinky") == "coily"      # kavyasreeb kinky -> our coily
    assert remap_label("AFRO") == "coily"
    assert remap_label("dreadlocks") is None    # style, dropped
    assert remap_label("mullet") is None        # unknown, dropped


def _touch(path):
    open(path, "w").close()


def test_build_samples_remaps_and_drops():
    with tempfile.TemporaryDirectory() as d:
        for cls, n in [("straight", 2), ("kinky", 1), ("dreadlocks", 1), ("random_junk", 1)]:
            os.makedirs(os.path.join(d, cls))
            for i in range(n):
                _touch(os.path.join(d, cls, f"{i}.jpg"))
        samples, kept, dropped = build_samples(d)

        assert kept == {"straight": 2, "coily": 1}            # kinky folded into coily
        assert dropped.get("dreadlocks") == 1 and dropped.get("random_junk") == 1
        assert len(samples) == 3
        # class indices map to our taxonomy
        idxs = {os.path.basename(os.path.dirname(p)): y for p, y in samples}
        assert idxs["straight"] == CLASS_INDEX["straight"]
        assert idxs["kinky"] == CLASS_INDEX["coily"]


def test_infer_degrades_without_model(monkeypatch):
    monkeypatch.delenv("KREY_HAIR_TEXTURE_MODEL", raising=False)
    out = read_hair_texture("/nonexistent.jpg")               # no model configured
    assert out == {"value": None, "available": False, "confidence": None}


def test_classes_are_the_texture_taxonomy():
    assert CLASSES == ["straight", "wavy", "curly", "coily"]


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
