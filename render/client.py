"""
Service A -> Service B render client. Pure stdlib (urllib), same discipline as app/notify.py
(no extra deps on the FastAPI service). Posts a person + garment image to the Modal endpoint
and returns the rendered PNG bytes. Configured entirely by env vars, so Service A stays inert
until the Modal endpoint is deployed and the vars are set.
"""
from __future__ import annotations
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid


def render_configured() -> bool:
    """True only when both the Modal URL and the shared secret are set."""
    return bool(os.environ.get("KREY_MODAL_RENDER_URL") and os.environ.get("KREY_RENDER_SECRET"))


def render_spawn(person_bytes: bytes, garment_bytes: bytes, cloth_type: str = "upper",
                 timeout: int = 60) -> str:
    """SPAWN a render on Modal (fire-and-poll). Returns a call_id immediately — the GPU job runs
    async, so no long-held HTTP connection (dodges Railway's 5-min no-data timeout)."""
    base = os.environ["KREY_MODAL_RENDER_URL"].rstrip("/")
    boundary = uuid.uuid4().hex
    body = _multipart(
        boundary,
        fields={"cloth_type": cloth_type},
        files={"person": ("person.jpg", person_bytes), "garment": ("garment.jpg", garment_bytes)},
    )
    req = urllib.request.Request(base + "/render", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("X-Krey-Secret", os.environ["KREY_RENDER_SECRET"])
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())["call_id"]


def render_poll(call_id: str, timeout: int = 30) -> bytes | None:
    """Poll a spawned render. Returns PNG bytes when ready, or None if still pending (HTTP 202)."""
    base = os.environ["KREY_MODAL_RENDER_URL"].rstrip("/")
    url = base + "/result?call_id=" + urllib.parse.quote(str(call_id))
    req = urllib.request.Request(url)
    req.add_header("X-Krey-Secret", os.environ["KREY_RENDER_SECRET"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status == 202:
                return None
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 202:
            return None
        raise


def render_tryon(person_bytes: bytes, garment_bytes: bytes, cloth_type: str = "upper",
                 timeout: int = 300) -> bytes:
    """Synchronous convenience: spawn then block-poll until ready. Kept for callers that want a
    single blocking call; the /closet flow uses spawn+poll directly so requests stay short."""
    import time
    call_id = render_spawn(person_bytes, garment_bytes, cloth_type)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        png = render_poll(call_id)
        if png is not None:
            return png
        time.sleep(3)
    raise TimeoutError("render did not complete in time")


def _multipart(boundary: str, fields: dict, files: dict) -> bytes:
    out = io.BytesIO()

    def w(s):
        out.write(s if isinstance(s, bytes) else s.encode())

    for name, value in fields.items():
        w(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n")
    for name, (filename, data) in files.items():
        w(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n")
        w("Content-Type: application/octet-stream\r\n\r\n")
        w(data)
        w("\r\n")
    w(f"--{boundary}--\r\n")
    return out.getvalue()
