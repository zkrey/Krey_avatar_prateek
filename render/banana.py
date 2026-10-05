"""
Krey "Nano Banana" render path — Google Gemini 2.5 Flash Image (a.k.a. nano-banana).

Unlike CatVTON (self-hosted VTON) and InstantID (self-hosted face+style), this is a frontier
CLOSED model reached over an API: it ingests BOTH the person photo AND the garment photo plus a
text instruction, and composes them in one pass — the only path that can plausibly deliver
"the real garment on the real you, styled" together. Trade-off: paid per-image, not owned, and
the images leave our infra (a privacy consideration for a body product — surface that to users).

Pure stdlib (urllib), same discipline as render/client.py — no new deps on Service A.
Config: set GEMINI_API_KEY on Service A (create a key at aistudio.google.com/apikey).
Gemini image generation is fast (~seconds), so callers use this synchronously (no fire-and-poll).
"""
from __future__ import annotations
import base64
import json
import os
import urllib.error
import urllib.request

MODEL = os.environ.get("KREY_BANANA_MODEL", "gemini-2.5-flash-image")
# A text/vision model (not the image model) for structured garment tagging. gemini-flash-latest
# returns clean JSON from a garment photo; override with KREY_TAG_MODEL.
TAG_MODEL = os.environ.get("KREY_TAG_MODEL", "gemini-flash-latest")
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def banana_configured() -> bool:
    """True only when a Gemini API key is set."""
    return bool(os.environ.get("GEMINI_API_KEY"))


def generate(person_bytes: bytes, garment_bytes: bytes | None, prompt: str,
             person_mime: str = "image/jpeg", garment_mime: str = "image/jpeg",
             timeout: int = 120) -> bytes:
    """Compose the person wearing the garment (+ style) via Gemini image. Returns PNG/JPEG bytes.
    Sends the person image first, the garment image second, then the text instruction."""
    key = os.environ["GEMINI_API_KEY"]
    url = _ENDPOINT.format(model=MODEL) + "?key=" + key
    parts = [
        {"inlineData": {"mimeType": person_mime, "data": base64.b64encode(person_bytes).decode()}},
    ]
    if garment_bytes:
        parts.append({"inlineData": {"mimeType": garment_mime,
                                     "data": base64.b64encode(garment_bytes).decode()}})
    parts.append({"text": prompt})
    body = json.dumps({"contents": [{"parts": parts}]}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"gemini {e.code}: {detail}")

    for cand in data.get("candidates", []):
        for part in (cand.get("content", {}) or {}).get("parts", []) or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    # no image came back — surface why (safety block, quota, prompt issue)
    reason = ""
    for cand in data.get("candidates", []):
        reason = cand.get("finishReason") or reason
    raise RuntimeError(f"gemini returned no image (finishReason={reason or '?'}): {json.dumps(data)[:300]}")


def tag_garment(image_bytes: bytes, mime: str = "image/jpeg", timeout: int = 60) -> dict:
    """Auto-catalogue a single garment photo → structured attributes via a Gemini vision model.
    Returns {name, cloth_type, color, pattern, formality, season} (best-effort; {} on failure)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not image_bytes:
        return {}
    url = _ENDPOINT.format(model=TAG_MODEL) + "?key=" + key
    prompt = ("Classify this single clothing item for a wardrobe catalogue. Return ONLY JSON with "
              "keys: name (short label, e.g. 'Navy blazer'), cloth_type (exactly one of: upper, "
              "lower, overall), color, pattern, formality (casual|smart|formal), season "
              "(summer|winter|all-season). No prose.")
    body = json.dumps({
        "contents": [{"parts": [
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(image_bytes).decode()}},
            {"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        txt = "".join(p.get("text", "") for c in data.get("candidates", [])
                      for p in (c.get("content", {}) or {}).get("parts", []))
        return json.loads(txt) if txt.strip() else {}
    except Exception:
        return {}
