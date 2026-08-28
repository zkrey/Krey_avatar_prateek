"""
Instagram source adapter — verified with STUB I/O (no Meta app, no token, no network,
no spend). Covers the pure filtering/ingest logic and the /capture/instagram endpoint
wiring (fetch + downstream pipeline monkeypatched).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app import instagram_source as ig
from app.main import app

client = TestClient(app)
ADULT = "1990-05-01"

NODES = [
    {"id": "1", "media_type": "IMAGE", "media_url": "https://cdn/i1.jpg", "timestamp": "2026-01-01T00:00:00+0000"},
    {"id": "2", "media_type": "VIDEO", "media_url": "https://cdn/v.mp4", "timestamp": "2026-01-02T00:00:00+0000"},
    {"id": "3", "media_type": "IMAGE", "media_url": "https://cdn/i2.jpg", "timestamp": "2026-01-03T00:00:00+0000"},
    {"id": "4", "media_type": "IMAGE"},   # no url -> dropped
]


def test_media_endpoint_is_the_graph_media_edge():
    url = ig.media_endpoint("178414")
    assert url.endswith("/178414/media") and url.startswith("https://graph.facebook.com/")


def test_image_media_keeps_only_still_images():
    imgs = ig.image_media(NODES)
    assert [m["id"] for m in imgs] == ["1", "3"]      # video + url-less dropped
    assert all("url" in m for m in imgs)


def test_fetch_caps_at_limit():
    fetcher = lambda uid, tok: NODES
    assert len(ig.fetch_account_images("u", "t", fetcher, limit=1)) == 1


def test_download_skips_failures():
    imgs = [{"url": "ok"}, {"url": "boom"}, {"url": "ok2"}]
    def dl(u):
        if u == "boom":
            raise RuntimeError("404")
        return b"bytes-" + u.encode()
    got = ig.download_images(imgs, dl)
    assert got == [b"bytes-ok", b"bytes-ok2"]


def test_ingest_end_to_end_with_stubs():
    raws = ig.ingest_from_instagram("u", "t",
                                    fetcher=lambda uid, tok: NODES,
                                    downloader=lambda url: b"img:" + url.encode())
    assert raws == [b"img:https://cdn/i1.jpg", b"img:https://cdn/i2.jpg"]   # 2 stills only


# ---- endpoint (fetch + pipeline monkeypatched -> hermetic) ----------------------------
def test_instagram_endpoint_blocks_without_account():
    r = client.post("/capture/instagram", json={"ig_user_id": "u", "access_token": "t",
                                                 "account_present": False})
    assert r.status_code == 403


def test_instagram_endpoint_needs_credentials():
    r = client.post("/capture/instagram", json={"account_present": True, "dob_verified": True,
                                                "birthdate": ADULT})
    assert r.status_code == 400


def test_instagram_endpoint_runs_through_the_auto_picker(monkeypatch):
    monkeypatch.setattr(ig, "ingest_from_instagram",
                        lambda *a, **k: [b"img1", b"img2", b"img3"])
    import app.capture_session as cs
    monkeypatch.setattr(cs, "analyze_capture", lambda paths: {
        "decision": "accept", "identity": {"overall": 0.8}, "timeline": {},
        "appearance": {"eye_colour": {"value": "dark_brown"}},
        "n_faces_total": 9, "n_user_faces": 5, "frames": []})
    r = client.post("/capture/instagram", json={"ig_user_id": "u", "access_token": "t",
                                                "account_present": True, "dob_verified": True,
                                                "birthdate": ADULT})
    assert r.status_code == 200
    b = r.json()
    assert b["source"] == "instagram" and b["n_sourced"] == 3 and b["decision"] == "accept"


def test_instagram_endpoint_no_images(monkeypatch):
    monkeypatch.setattr(ig, "ingest_from_instagram", lambda *a, **k: [])
    r = client.post("/capture/instagram", json={"ig_user_id": "u", "access_token": "t",
                                                "account_present": True, "dob_verified": True,
                                                "birthdate": ADULT})
    assert r.status_code == 200 and r.json()["decision"] == "retake_no_images"


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
