"""Compact-twin store — save/merge/get/delete, and the derive-and-discard whitelist."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app import store


def test_save_requires_an_account():
    with pytest.raises(ValueError):
        store.MemoryTwinStore().save("", {"skin_tone": {"value": 6}})


def test_whitelist_drops_raw_and_unknown_fields():
    # anything not a known body_models slot (e.g. a stray raw payload) must never persist.
    s = store.MemoryTwinStore()
    env = s.save("u1", {"skin_tone": {"value": 6}, "raw_photo": b"xxxx", "embedding": [0.1] * 512})
    assert set(env["record"]) == {"skin_tone"}
    assert env["raw_retained"] is False


def test_face_then_body_merge_into_one_twin():
    s = store.MemoryTwinStore()
    s.save("u1", {"skin_tone": {"value": 6}, "eye_colour": {"value": "dark_brown"}}, source="capture")
    env = s.save("u1", {"measurements": {"waist": {"circumference_cm": 81}}}, source="body")
    assert set(env["record"]) == {"skin_tone", "eye_colour", "measurements"}   # accumulated
    assert env["version"] == 2 and env["last_source"] == "body"


def test_created_at_stable_updated_at_moves():
    s = store.MemoryTwinStore()
    a = s.save("u1", {"skin_tone": {"value": 6}})
    b = s.save("u1", {"hair_colour": {"value": "black"}})
    assert b["created_at"] == a["created_at"] and b["version"] == 2


def test_get_and_erasure():
    s = store.MemoryTwinStore()
    assert s.get("u1") is None
    s.save("u1", {"skin_tone": {"value": 6}})
    assert s.exists("u1") and s.get("u1")["record"]["skin_tone"]["value"] == 6
    assert s.delete("u1") is True and s.get("u1") is None
    assert s.delete("u1") is False        # erasure is idempotent


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
