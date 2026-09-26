"""
Krey avatar sub-project — Service A: twin-extraction API.

Two GPU-free extraction slices that fill the body_models record (spec §4):
  - slice 1  POST /twin/extract-skin          -> skin_tone slice (deterministic Monk)
  - slice 2  POST /twin/extract-measurements  -> measurements + shape + accuracy ledger

Every call emits a structured analytics event carrying the common spine (see
app/analytics.py) — "the gates are the events". Eligibility is NOT enforced here: per
the invariants, account + verified-DOB gating lives at the single `canRender` chokepoint
(slice 3), never scattered per feature.

Run locally:
    pip install -r requirements.txt
    uvicorn app.main:app --reload
    # skin:          curl -F "file=@face.jpg" http://127.0.0.1:8000/twin/extract-skin
    # measurements:  curl -F "file=@body.jpg" -F height=170 -F weight=65 -F sex=2 \\
    #                     http://127.0.0.1:8000/twin/extract-measurements
"""
from __future__ import annotations
import json
import logging
import os
import uuid
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body, BackgroundTasks, Header
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

from datetime import date, datetime

from app import monk
from app import feedback as feedback_mod
from app.skin_tone import extract_skin_samples
from app import measurements as body
from app import face
from app import eligibility, style_profile, fit_score, entitlements
from app import notify
from app import store as store_mod
from app.body_models import assemble_body_models
from app.analytics import Analytics, Spine, ENTRY_POINTS as analytics_entry_points
from app.recognition import recognition_from_body_models

app = FastAPI(title="Krey Avatar — Service A (twin extraction)", version="0.5.0")

# Surface the krey.* diagnostic loggers (capture/body/notify) at INFO. Setting the level
# alone wasn't enough — with no INFO-level handler these records fell through to Python's
# lastResort handler, which only emits WARNING+, so every INFO (email-sent, read summaries)
# was silently dropped. Attach an explicit stdout handler so they actually reach the logs.
_krey_log = logging.getLogger("krey")
_krey_log.setLevel(logging.INFO)
if not _krey_log.handlers:
    _kh = logging.StreamHandler()
    _kh.setFormatter(logging.Formatter("%(levelname)s:%(name)s: %(message)s"))
    _krey_log.addHandler(_kh)
    _krey_log.propagate = False


@app.on_event("startup")
def _warm_models():
    """Load the identity model at boot in a background thread so the first real /capture
    doesn't pay a ~25s cold load. Best-effort; ignored if the CV stack isn't present."""
    import threading

    def _go():
        try:
            from app import capture_session as cs
            cs._get_app()
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()

# Permissive CORS so the team QA page (/tester) works whether served here or opened locally
# against a deployed URL. Tighten to the real client origin before production.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])

_WEBTEST = os.path.join(os.path.dirname(__file__), "webtest.html")
_ALPHA = os.path.join(os.path.dirname(__file__), "alpha.html")
_CLOSET = os.path.join(os.path.dirname(__file__), "closet.html")
_LOOK = os.path.join(os.path.dirname(__file__), "look.html")
_RANK = os.path.join(os.path.dirname(__file__), "rank.html")
_STUDIO = os.path.join(os.path.dirname(__file__), "studio.html")
_RESULTS = os.path.join(os.path.dirname(__file__), "results.html")
_ADMIN = os.path.join(os.path.dirname(__file__), "admin.html")


def _render_template(path: str, title: str, og_title: str, og_image: str, data: dict) -> str:
    """Fill a landing-page template's OG tags (server-side, so link crawlers see them) + inject
    its data blob. Kept dead simple — token replacement, no template engine dependency."""
    import html as _html
    with open(path, encoding="utf-8") as f:
        tpl = f.read()
    return (tpl.replace("__TITLE__", _html.escape(title))
               .replace("__OG_TITLE__", _html.escape(og_title))
               .replace("__OG_IMAGE__", _html.escape(og_image or ""))
               .replace("__DATA__", json.dumps(data)))


@app.get("/tester", response_class=HTMLResponse)
def tester():
    """Team QA page: upload a photo → see the extracted twin pointers (Monk tone, hair, eye,
    body measurements) from the real endpoints; a Fit tab runs the rule engine offline.
    Served by the backend so the Twin tab can call the same-origin extraction endpoints."""
    with open(_WEBTEST, encoding="utf-8") as f:
        return f.read()


@app.get("/alpha", response_class=HTMLResponse)
def alpha():
    """Alpha-user Twin Check: add up to 5 photos → owner is picked (/capture/session) and the
    twin read shown (skin/hair/eye/shape/proportions, + measurements when height is given via
    /body/measure); low-confidence fields ask a one-tap confirm, and any wrong value is flagged
    back to the team via /feedback. Same-origin so the page calls the extraction endpoints
    directly. GPU-free: the pipeline stops before any render (Service B)."""
    with open(_ALPHA, encoding="utf-8") as f:
        return f.read()


@app.get("/closet", response_class=HTMLResponse)
def closet():
    """Browse the garment catalog (the try-on 'supply' side). Reads /closet/garments, which is
    Supabase-backed when configured, else a built-in sample set. 'Try on' wires to the render
    (Service B) once it's live."""
    with open(_CLOSET, encoding="utf-8") as f:
        return f.read()


@app.get("/closet/garments")
def closet_garments(cloth_type: Optional[str] = None, segment: Optional[str] = None):
    """Catalog JSON for the closet UI. Filterable by cloth_type (render dimension) and segment
    (analytics dimension: intimate/wedding/ethnic/...). `render_live` tells the page whether
    'see it on you' works yet (true only once the Modal render backend is configured)."""
    from app import catalog as catalog_mod
    try:
        from render import client as render_client
        render_live = render_client.render_configured()
    except Exception:
        render_live = False   # render/ package not on the image yet — never 500 the closet
    return {
        "garments": catalog_mod.list_garments(cloth_type, segment),
        "source": "supabase" if catalog_mod.catalog_configured() else "sample",
        "segments": list(catalog_mod.SEGMENTS),
        "render_live": render_live,
    }


@app.post("/closet/event")
def closet_event(payload: dict = Body(...)):
    """Log a view/try/share against a garment — the 'what gets shared most' thesis.

    Durable (Supabase garment_events); best-effort so the browse UI never blocks on it.
    Body: {garment_id, event_type in view|try|share, segment?, cloth_type?, session_hint?}.
    """
    from app import catalog as catalog_mod
    ok = catalog_mod.log_event(
        garment_id=str(payload.get("garment_id") or ""),
        event_type=str(payload.get("event_type") or ""),
        segment=payload.get("segment"),
        cloth_type=payload.get("cloth_type"),
        session_hint=payload.get("session_hint"),
        channel=payload.get("channel"),
        referrer_hint=payload.get("referrer_hint"),
    )
    return {"logged": bool(ok)}


# --- the share -> rank -> confidence -> referral loop (social-testing experiment) ---

@app.get("/look/{look_id}", response_class=HTMLResponse)
def look_page(look_id: str):
    """Public share page for one rendered look. OG tags (server-filled) make the link unfurl
    into a thumbnail in WhatsApp/IG/X; the page carries the 'try your own fit' referral CTA."""
    from app import catalog as catalog_mod
    look = catalog_mod.get_look(look_id) or {"look_id": look_id, "name": None,
                                             "image_url": None, "owner_hint": None}
    name = look.get("name") or "A look"
    return _render_template(
        _LOOK, title=f"{name} · Krey", og_title=f"{name} on Krey ✨",
        og_image=look.get("image_url") or "",
        data={"look_id": look.get("look_id"), "name": look.get("name"),
              "image_url": look.get("image_url"), "owner_hint": look.get("owner_hint")})


@app.get("/rank/{set_id}", response_class=HTMLResponse)
def rank_page(set_id: str):
    """Pairwise ballot: friends tap the better look (no signup). OG-unfurls to a preview; ends on
    the 'try your own fit' referral CTA. Feeds rank_votes -> Glicko-2 (offline)."""
    from app import catalog as catalog_mod
    rs = catalog_mod.get_rank_set(set_id)
    if not rs:
        rs = {"set_id": set_id, "owner_hint": None, "ref": None, "name": None, "looks": []}
    og_img = ""
    for l in rs.get("looks", []):
        if l.get("image_url"):
            og_img = l["image_url"]; break
    name = rs.get("name") or "a friend"
    return _render_template(
        _RANK, title="Rank these fits · Krey", og_title=f"Help {name} pick the best fit 👗",
        og_image=og_img,
        data={"set_id": rs.get("set_id"), "owner_hint": rs.get("owner_hint"),
              "ref": rs.get("ref"), "name": rs.get("name"), "looks": rs.get("looks", [])})


@app.get("/rank/{set_id}/next")
def rank_next(set_id: str, seen: Optional[str] = None):
    """Mixed adaptive sampler: the next pair to show this voter (concurrency-safe). `seen` is a
    comma list of 'a|b' pair keys already shown. Returns {a,b,remaining} or {done:true}."""
    from app import catalog as catalog_mod
    seen_set = set((seen or "").split(",")) - {""}
    pair = catalog_mod.next_pair(set_id, seen_set)
    return pair or {"done": True}


@app.post("/rank/vote")
def rank_vote(payload: dict = Body(...)):
    """Record one pairwise vote / reaction (anonymous). Best-effort."""
    from app import catalog as catalog_mod
    ok = catalog_mod.record_vote(
        set_id=str(payload.get("set_id") or ""),
        winner_look_id=str(payload.get("winner_look_id") or ""),
        loser_look_id=payload.get("loser_look_id"),
        voter_hint=payload.get("voter_hint"),
        referrer_hint=payload.get("referrer_hint"),
    )
    return {"logged": bool(ok)}


@app.post("/referral")
def referral(payload: dict = Body(...)):
    """Record a referred visit or an activation (K-factor edge). Best-effort."""
    from app import catalog as catalog_mod
    ok = catalog_mod.record_referral(
        referrer_hint=str(payload.get("referrer_hint") or ""),
        visitor_hint=payload.get("visitor_hint"),
        source=payload.get("source"),
        activated=bool(payload.get("activated", False)),
    )
    return {"logged": bool(ok)}


# --- self-serve: upload your own outfit photos -> ballot -> share (runs without the render) ---

@app.get("/studio", response_class=HTMLResponse)
def studio():
    """Create a 'rate my fit' ballot from your own outfit photos, then share it. Works today with
    no GPU render — the generative try-on is a later layer, not a dependency for the social test."""
    with open(_STUDIO, encoding="utf-8") as f:
        return f.read()


@app.post("/studio/create")
async def studio_create(
    name: str = Form(...),
    owner_hint: str = Form(...),
    files: list[UploadFile] = File(...),
    confidence_self: Optional[int] = Form(None),
    confidences: Optional[str] = Form(None),   # per-file self-confidence, aligned to files order
    ref: Optional[str] = Form(None),
):
    """Upload 2–3 outfit photos, store them, bundle into a ballot, return the share + results URLs."""
    from app import catalog as catalog_mod
    if not catalog_mod.catalog_configured():
        raise HTTPException(503, "catalog store not configured")
    imgs = [f for f in (files or [])][:3]
    if len(imgs) < 2:
        raise HTTPException(400, "add at least 2 photos")
    conf_list: list[Optional[int]] = []
    if confidences:
        for tok in confidences.split(","):
            try:
                conf_list.append(int(tok))
            except Exception:
                conf_list.append(None)
    look_ids: list[str] = []
    for i, up in enumerate(imgs):
        data = await up.read()
        if not data:
            continue
        ct = up.content_type or "image/jpeg"
        ext = "png" if "png" in ct else "webp" if "webp" in ct else "jpg"
        url = catalog_mod.upload_image(data, content_type=ct, ext=ext)
        c = conf_list[i] if i < len(conf_list) else confidence_self
        lid = catalog_mod.create_look(owner_hint=owner_hint, name=f"{name} · fit {i+1}",
                                      image_url=url, confidence_self=c)
        if lid:
            look_ids.append(lid)
    if len(look_ids) < 2:
        raise HTTPException(502, "could not store the looks — check the Storage bucket + policy")
    set_id = catalog_mod.create_rank_set(owner_hint=owner_hint, look_ids=look_ids,
                                         name=name, ref=ref or owner_hint)
    if not set_id:
        raise HTTPException(502, "could not create the ballot")
    return {"set_id": set_id, "share_url": f"/rank/{set_id}", "results_url": f"/results/{set_id}"}


@app.get("/results/{set_id}", response_class=HTMLResponse)
def results_page(set_id: str):
    """The owner's view: how friends ranked their fits (drives the confidence payoff)."""
    return _render_template(_RESULTS, title="Your results · Krey",
                            og_title="My Krey results", og_image="", data={"set_id": set_id})


@app.get("/results/{set_id}/data")
def results_data(set_id: str):
    """Vote tallies for a ballot (win-rate per look)."""
    from app import catalog as catalog_mod
    return catalog_mod.get_results(set_id) or {"set_id": set_id, "looks": [], "votes": 0}


@app.post("/results/confidence")
def results_confidence(payload: dict = Body(...)):
    """Record a post-rank fit-confidence tap (phase='post') — the Δconfidence signal."""
    from app import catalog as catalog_mod
    ok = catalog_mod.record_confidence(
        set_id=payload.get("set_id"), look_id=payload.get("look_id"),
        owner_hint=payload.get("owner_hint"), phase=str(payload.get("phase") or "post"),
        value=payload.get("value"),
    )
    return {"logged": bool(ok)}


# --- analytics dashboard (token-gated) ---

def _admin_authed(token: Optional[str]) -> bool:
    want = os.environ.get("KREY_ADMIN_TOKEN")
    return bool(want) and token == want


@app.get("/admin", response_class=HTMLResponse)
def admin_page(token: Optional[str] = None):
    """Private analytics: Glicko-2 leaderboard, K-factor, confidence lift, share funnel.
    Gated by ?token=... matching KREY_ADMIN_TOKEN (set it on Railway)."""
    if not os.environ.get("KREY_ADMIN_TOKEN"):
        raise HTTPException(503, "set KREY_ADMIN_TOKEN on the server to enable /admin")
    if not _admin_authed(token):
        raise HTTPException(401, "add ?token=YOUR_ADMIN_TOKEN")
    return _render_template(_ADMIN, title="Krey · Admin", og_title="Krey Admin",
                            og_image="", data={"token": token})


@app.get("/admin/data")
def admin_data(token: Optional[str] = None):
    """JSON snapshot for the admin dashboard (same token gate)."""
    from app import catalog as catalog_mod
    if not _admin_authed(token):
        raise HTTPException(401, "bad token")
    return catalog_mod.admin_snapshot()

# Default sink logs JSON lines; swap for the warehouse / Events service in production.
analytics = Analytics()
# Compact-record store (derive-and-discard). In-memory reference; swap for a DB backend.
twin_store = store_mod.MemoryTwinStore()


def _twin_from_appearance(appearance: Optional[dict]) -> dict:
    """Assemble a compact body_models (face slices + recognition) from fused capture attrs."""
    a = appearance or {}
    def cslot(name):
        n = a.get(name)
        return {"value": n["value"], "confidence": n.get("confidence")} \
            if n and n.get("value") is not None else None
    ht = a.get("hair_texture")
    hair_texture = ({"value": ht["value"], "available": True, "confidence": ht.get("confidence")}
                    if ht and ht.get("value") is not None else None)
    rec = assemble_body_models(skin_tone=cslot("skin_tone"), hair_colour=cslot("hair_colour"),
                               hair_texture=hair_texture, eye_colour=cslot("eye_colour"))
    rec["avatar_confidence"] = recognition_from_body_models(rec)
    return rec


def _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, entry_point) -> Spine:
    """Build the analytics spine from client-provided context, with safe demo defaults."""
    if not user_id and not guest_id:
        guest_id = f"guest-{uuid.uuid4().hex[:12]}"
    return Spine(
        session_id=session_id or f"sess-{uuid.uuid4().hex[:12]}",
        surface=surface or "onboarding",
        app_version=app_version or "0.0.0",
        device_os=device_os or "unknown",
        signed_in=bool(user_id),
        user_id=user_id,
        guest_id=guest_id,
        entry_point=entry_point,
        region=region,
    )


def _biometric_gate(account_present: bool, dob_verified: bool, birthdate: Optional[str],
                    jurisdiction: Optional[str]):
    """
    The single canRender chokepoint, applied at every biometric-INGESTION entry (photos in).
    Twin-building spends no tokens, so render_cost=0; the wall still enforces account +
    verified DOB + the jurisdiction age policy (minors blocked) before any biometric is read.
    Returns the Eligibility verdict; the caller 403s when not allowed. Same rule everywhere —
    the policy lives only in app/eligibility.py, never re-implemented per endpoint.
    """
    bd = None
    if birthdate:
        try:
            bd = date.fromisoformat(birthdate)
        except ValueError:
            bd = None
    return eligibility.can_render(
        account_present=account_present, dob_verified=dob_verified, birthdate=bd,
        today=date.today(), token_balance=0, render_cost=0,
        jurisdiction=jurisdiction or eligibility.M1_JURISDICTION,
        input_eligibility_passed=True,
    )


# Cap the longest edge of ingested photos before the CV pipelines touch them. Phone
# photos are commonly 3000-4000px (~36 MB once decoded to RGB); on a 1 GB host the peak
# of image decode + buffalo_l + onnxruntime OOM-kills the container mid-read. Downscaling
# to <= this many px cuts peak RAM several-fold and is safe for the algorithm: body
# measurements scale off the *declared height* (a proportional resize preserves every
# ratio), and skin/hair/eye are LAB colour reads (resize doesn't move colour), while a
# face stays far above detection/recognition resolution. Override via KREY_MAX_IMAGE_PX.
DOWNSCALE_MAX_PX = int(os.environ.get("KREY_MAX_IMAGE_PX") or "1600")


def _downscale_jpeg(raw: bytes, max_px: int = DOWNSCALE_MAX_PX) -> bytes:
    """Best-effort: return an EXIF-oriented JPEG capped to max_px on its longest edge.
    Returns the original bytes unchanged on any failure (e.g. a format PIL can't read),
    so ingestion never breaks — worst case is the pre-existing full-size behaviour."""
    try:
        import io
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(raw)) as im:
            # draft() lets the JPEG decoder emit a reduced image without a full-res decode
            # first — this is the real memory saving, not just the final resize.
            try:
                im.draft("RGB", (max_px, max_px))
            except Exception:
                pass
            im = ImageOps.exif_transpose(im)          # honour phone rotation
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            w, h = im.size
            if max(w, h) > max_px:
                s = max_px / float(max(w, h))
                im = im.resize((max(1, round(w * s)), max(1, round(h * s))))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=85, optimize=True)
            return out.getvalue()
    except Exception:
        return raw


def _save_uploads(raws) -> list:
    """Write in-memory uploads to short-lived temp files (paths for the cv2 pipelines).
    Images are downscaled on the way in (see _downscale_jpeg) to survive small hosts.
    The caller MUST delete them after processing — derive-and-discard: raw biometrics are
    never retained past the extraction that derives the compact record."""
    import tempfile
    paths = []
    d = tempfile.mkdtemp(prefix="krey-capture-")
    for i, raw in enumerate(raws):
        p = os.path.join(d, f"img_{i}.jpg")
        with open(p, "wb") as f:
            f.write(_downscale_jpeg(raw))
        paths.append(p)
    return paths, d


def _discard(paths, d):
    """Delete the raw photos + their temp dir. Best-effort; never raises."""
    import shutil
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


@app.get("/health")
def health():
    return {"status": "ok", "service": "twin-extraction",
            "slices": ["skin-tone-v0", "measure-v0", "face-v0"],
            "flows": ["capture-session", "body-measure", "fit-recommend", "style-profile"]}


@app.post("/twin/extract-skin")
async def extract_skin(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    guest_id: Optional[str] = Form(None),
    surface: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    device_os: Optional[str] = Form(None),
):
    import cv2  # lazy: keeps module import light

    spine = _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, None)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not decode image")

    found = extract_skin_samples(img)
    if not found["ok"]:
        # No usable face -> Stage-0 retake signal; emit it.
        analytics.input_cascade(spine, passed=False, stage=0, quality_flags=["no_face"])
        return {
            "eligibility": {"passed": False, "stage": 0, "quality_flags": ["no_face"]},
            "monk_tone": None,
        }

    monk_tone = monk.classify(found["samples"])
    analytics.twin_extracted(spine, slice="skin", model=monk_tone["model"],
                             confidence=monk_tone["confidence"], needs_confirm=monk_tone["needs_confirm"])
    return {
        "eligibility": {"passed": True, "stage": 2, "quality_flags": []},
        "monk_tone": monk_tone,
        "detector": found["detector"],
    }


@app.post("/twin/extract-face")
async def extract_face(
    file: UploadFile = File(...),          # front-face photo
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    guest_id: Optional[str] = Form(None),
    surface: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    device_os: Optional[str] = Form(None),
):
    """
    Compose the FACE portion of body_models — skin_tone (built) + hair/eye slices
    (model-backed, degrade cleanly to a stub until the hair/iris samplers are wired).
    One photo in; skin + whatever face attributes we can read + the §6 recognition
    score out. Eligibility stays at the single canRender chokepoint, not here.
    """
    import cv2  # lazy: keeps module import light

    spine = _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, None)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not decode image")

    # Single-clear-face gate FIRST: no face / multiple faces -> retake, trust nothing.
    sig = face.sample_face(img)
    if sig["gate"] != "ok":
        analytics.input_cascade(spine, passed=False, stage=0, quality_flags=[sig["gate"]])
        return {
            "eligibility": {"passed": False, "stage": 0, "quality_flags": [sig["gate"]]},
            "n_faces": sig["n_faces"],
            "body_models": None,
        }

    hair_features = (face.hair.texture_features_from_region(sig["hair_region"])
                     if sig["hair_region"] is not None else None)
    record = face.assemble_face(skin_samples=sig["skin_samples"] or None,
                                hair_samples=sig["hair_samples"] or None,
                                iris_samples=sig["iris_samples"] or None,
                                hair_features=hair_features,
                                hair_region=sig["hair_region"])   # used only if a texture model is configured

    present = face.face_slices_present(record)
    if not present:
        analytics.input_cascade(spine, passed=False, stage=0, quality_flags=["no_attributes"])
        return {
            "eligibility": {"passed": False, "stage": 0, "quality_flags": ["no_attributes"]},
            "n_faces": sig["n_faces"],
            "body_models": None,
        }

    analytics.twin_extracted(spine, slice="face", model="face-compose-v0",
                             confidence=record["avatar_confidence"]["overall"])
    return {
        "eligibility": {"passed": True, "stage": 2, "quality_flags": []},
        "slices_present": present,
        "n_faces": sig["n_faces"],
        "body_models": record,
    }


@app.post("/twin/extract-measurements")
async def extract_measurements(
    file: UploadFile = File(...),          # front-body photo
    height: float = Form(...),             # declared height (cm) — the scale anchor
    weight: float = Form(...),             # declared weight (kg) — for BMI
    sex: int = Form(...),                  # 1 = male, 2 = female
    body_type: Optional[str] = Form(None), # declared body_type — CROSS-CHECK only
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    guest_id: Optional[str] = Form(None),
    surface: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    device_os: Optional[str] = Form(None),
):
    import cv2  # lazy: keeps module import light

    spine = _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, None)

    # The pose model is large and licensed separately; it is not bundled in the repo.
    if not os.path.exists(body._model_path()):
        raise HTTPException(503, f"pose model not found at {body._model_path()} "
                                 "(set MODELS_DIR to the folder holding pose_landmarker_heavy.task)")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not decode image")

    result = body.compute_measurements(
        img, declared_height_cm=height, declared_weight_kg=weight,
        sex=sex, declared_body_type=body_type,
    )
    if result["status"] != "ok":
        analytics.input_cascade(spine, passed=False, stage=0, quality_flags=[result["reason"]])
        return {
            "eligibility": {"passed": False, "stage": 0, "quality_flags": [result["reason"]]},
            "body_models": None,
        }

    # Attach the §6 recognition score (partial coverage until hair/eye slices exist).
    record = result["body_models"]
    record["avatar_confidence"] = recognition_from_body_models(record)
    analytics.twin_extracted(spine, slice="measurements", model="rule-measure-v0",
                             confidence=record["accuracy_ledger"]["body_confidence"])
    return {
        "eligibility": {"passed": True, "stage": 2, "quality_flags": []},
        "scale_px_per_cm": result["scale_px_per_cm"],
        "body_models": record,
    }


# ===========================================================================
# Consolidated flows — the real Service A surface (multi-photo + fit).
# Each biometric-ingestion flow passes the single canRender chokepoint first,
# then derives the compact record and DISCARDS the raw photos.
# ===========================================================================
@app.post("/capture/session")
async def capture_session_ep(
    files: list[UploadFile] = File(...),           # the capture set (e.g. 5 photos)
    account_present: bool = Form(False),
    dob_verified: bool = Form(False),
    birthdate: Optional[str] = Form(None),         # ISO YYYY-MM-DD
    jurisdiction: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    guest_id: Optional[str] = Form(None),
    surface: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    device_os: Optional[str] = Form(None),
):
    """
    Consolidate a capture set into one twin: detect + match identity, pick the owner,
    fuse face attributes (recency-weighted, outlier-robust), and return the soft-confirm
    decision. Gated at entry (biometric ingestion); raw photos are discarded after.
    """
    spine = _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, None)
    gate = _biometric_gate(account_present, dob_verified, birthdate, jurisdiction)
    analytics.eligibility(spine, allowed=gate.allowed, reason=gate.reason)
    if not gate.allowed:
        raise HTTPException(403, {"reason": gate.reason, "is_minor": gate.is_minor})

    raws = [r for r in [await f.read() for f in files] if r]
    if not raws:
        raise HTTPException(400, "no images")
    paths, d = _save_uploads(raws)
    try:
        from app import capture_session as cs
        result = cs.analyze_capture(paths)
    finally:
        _discard(paths, d)                          # derive-and-discard

    conf = (result.get("identity") or {}).get("overall")
    analytics.twin_extracted(spine, slice="capture", model="capture-aggregate-v0", confidence=conf)
    saved = False
    if spine.user_id and result.get("appearance"):          # persist only for an account
        twin_store.save(spine.user_id, _twin_from_appearance(result["appearance"]), source="capture")
        saved = True
    return {
        "eligibility": {"passed": True, "reason": "ok"},
        "decision": result["decision"],
        "identity": result["identity"],
        "timeline": result["timeline"],
        "appearance": result["appearance"],
        "owner_thumb": result.get("owner_thumb"),   # transient crop of the picked owner face
        "n_faces_total": result["n_faces_total"],
        "n_user_faces": result["n_user_faces"],
        "saved": saved,
    }


@app.post("/body/measure")
async def body_measure_ep(
    files: list[UploadFile] = File(...),           # full-body frames
    height: float = Form(...),                     # declared height (cm) — scale anchor
    weight: float = Form(...),
    sex: int = Form(...),                          # 1 = male, 2 = female
    body_type: Optional[str] = Form(None),
    account_present: bool = Form(False),
    dob_verified: bool = Form(False),
    birthdate: Optional[str] = Form(None),
    jurisdiction: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    guest_id: Optional[str] = Form(None),
    surface: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    device_os: Optional[str] = Form(None),
):
    """Consolidate build across full-body frames (gated, recency-weighted, robust). Height
    is the scale anchor. Non-measurable frames are dropped; raw photos discarded after."""
    spine = _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, None)
    gate = _biometric_gate(account_present, dob_verified, birthdate, jurisdiction)
    analytics.eligibility(spine, allowed=gate.allowed, reason=gate.reason)
    if not gate.allowed:
        raise HTTPException(403, {"reason": gate.reason, "is_minor": gate.is_minor})

    if not os.path.exists(body._model_path()):
        raise HTTPException(503, f"pose model not found at {body._model_path()} "
                                 "(set MODELS_DIR to the folder holding pose_landmarker_heavy.task)")

    raws = [r for r in [await f.read() for f in files] if r]
    if not raws:
        raise HTTPException(400, "no images")
    # Free the identity + face-parse models before the pose pass: on a 1 GB host all three
    # model families can't sit resident together (the pose step OOM-killed the container even
    # in-process). They rebuild lazily on the next capture. Best-effort.
    try:
        from app import face_pipeline as _fp
        _fp.release_models()
        from app import capture_session as _cs
        _cs.release_app()
    except Exception:
        pass
    paths, d = _save_uploads(raws)
    try:
        from app import body_session as bs
        result = bs.analyze_body(paths, declared_height_cm=height, declared_weight_kg=weight,
                                 sex=sex, declared_body_type=body_type)
    finally:
        _discard(paths, d)                          # derive-and-discard

    ledger = result.get("accuracy_ledger")
    analytics.twin_extracted(spine, slice="measurements", model="rule-measure-v0",
                             confidence=(ledger or {}).get("body_confidence", 0.0))
    saved = False
    if spine.user_id and result.get("measurements"):        # persist only for an account
        twin_store.save(spine.user_id, assemble_body_models(
            measurements=result["measurements"], body_shape=result["body_shape"],
            accuracy_ledger=ledger), source="body")
        saved = True
    return {
        "eligibility": {"passed": True, "reason": "ok"},
        "decision": result["decision"],
        "n_measurable": result["n_measurable"],
        "timeline": result["timeline"],
        "measurements": result["measurements"],
        "body_shape": result["body_shape"],
        "accuracy_ledger": ledger,
        "saved": saved,
    }


@app.get("/twins/{user_id}")
def get_twin(user_id: str):
    """Fetch the stored compact twin for an account (the derived record, never raw photos)."""
    env = twin_store.get(user_id)
    if not env:
        raise HTTPException(404, "no twin stored for this user")
    return env


@app.delete("/twins/{user_id}")
def delete_twin(user_id: str):
    """Right-to-erasure (DPDP): delete the stored twin entirely."""
    return {"erased": twin_store.delete(user_id)}


@app.post("/style/profile")
def style_profile_ep(payload: dict = Body(...)):
    """Assemble a StyleProfile from the quick-tap intake (fit_feel, sizes, region prefs).
    No biometrics, no LLM — the free-text nuance layer plugs in via app/style_intake.py."""
    prof = style_profile.assemble_style_profile(
        fit_feel=payload.get("fit_feel"),
        region_preferences=payload.get("region_preferences"),
        comfort_offset=payload.get("comfort_offset"),
        sensitivities=payload.get("sensitivities"),
        confidence_notes=payload.get("confidence_notes"),
        source=payload.get("source", "single_input"),
    )
    return {"style_profile": prof}


@app.post("/fit/recommend")
def fit_recommend_ep(payload: dict = Body(...)):
    """
    Best-match size for a garment, given the user's body + StyleProfile. GPU-free maths on
    already-derived data (no biometric ingestion), so no render gate. Returns the size, the
    per-region verdict, and a user-facing `why` that never names an insecurity.
    """
    body_cm = payload.get("body_cm")
    if body_cm is None and payload.get("measurements"):
        body_cm, _ = fit_score.from_body_models(payload["measurements"])
    garment = payload.get("garment")
    if not body_cm or not garment or "size_chart" not in garment:
        raise HTTPException(400, "need body_cm (or measurements) and a garment with a size_chart")
    return fit_score.recommend_for_style(
        {k: float(v) for k, v in body_cm.items()}, garment,
        style_profile=payload.get("style_profile"), confidence=payload.get("confidence"))


@app.post("/render/authorize")
def render_authorize_ep(payload: dict = Body(...)):
    """
    The play-loop gate. Before each try-on render the client asks: may this plan render
    now, in which GPU lane, how many are left today, and is this the moment to offer more?

    Same product for every plan — this decides only QUOTA and SPEED (the two subscription
    levers). `used_today` is the caller's daily counter (from the store/DB); this endpoint
    is pure policy, spends no GPU, and returns instantly. It sits ALONGSIDE the canRender
    eligibility wall (account + DOB), which the actual render worker still enforces — this
    says *may this plan render now, and how fast*, not *may this person render at all*.

    The `upsell` block fires only after the wow inflection and only at the quota wall, so a
    free user converts at the peak of the experience, never nagged before the magic lands.
    """
    plan = payload.get("plan")
    used_today = int(payload.get("used_today") or 0)
    decision = entitlements.authorize(plan, used_today)

    # Record intent when a valid play surface is named (feeds the render funnel + unit econ).
    entry_point = payload.get("entry_point")
    if entry_point in analytics_entry_points:
        spine = _spine(payload.get("session_id"), payload.get("user_id"), payload.get("guest_id"),
                       payload.get("surface"), payload.get("region"), payload.get("app_version"),
                       payload.get("device_os"), None)
        analytics.render(spine, phase="requested", entry_point=entry_point,
                         fail_reason=None if decision["allowed"] else "daily_quota_reached",
                         source=decision["lane"])
    return decision


@app.post("/render")
async def render_ep(
    person: UploadFile = File(...),                 # the person photo (real-world OK; auto-cropped)
    garment: UploadFile = File(...),                # the garment image (flat-lay or on-model)
    cloth_type: str = Form("upper"),                # upper (tops-first v1) | lower | overall
    entry_point: str = Form("tap"),                 # play surface that triggered this render
    plan: Optional[str] = Form(None),
    used_today: int = Form(0),
    token_balance: int = Form(0),
    account_present: bool = Form(False),
    dob_verified: bool = Form(False),
    birthdate: Optional[str] = Form(None),
    jurisdiction: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    guest_id: Optional[str] = Form(None),
    surface: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    device_os: Optional[str] = Form(None),
):
    """
    The try-on render (Service B). Doctrine intact: eligibility (canRender) + token hold live
    HERE on Service A; the GPU runs on Modal (render/modal_app.py) which auto-crops + composites
    so real-world photos work and only the garment pixels change. Derive-and-discard: images in,
    PNG out, nothing stored. Inert (503) until KREY_MODAL_RENDER_URL + KREY_RENDER_SECRET are set,
    so this is safe to ship dark and light up when the Modal endpoint is deployed.
    """
    import time
    from render import client as render_client
    if not render_client.render_configured():
        raise HTTPException(503, "render backend not configured")

    spine = _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, None)
    ep = entry_point if entry_point in analytics_entry_points else "tap"

    # 1) daily quota + lane (pure policy) — same call /render/authorize uses.
    authz = entitlements.authorize(plan, used_today)
    if not authz["allowed"]:
        analytics.render(spine, phase="requested", entry_point=ep,
                         fail_reason="daily_quota_reached", source=authz.get("lane"))
        raise HTTPException(429, {"reason": "daily_quota_reached", "upsell": authz.get("upsell")})

    # 2) the single canRender wall (account + DOB + jurisdiction + funds).
    bd = None
    if birthdate:
        try:
            bd = date.fromisoformat(birthdate)
        except ValueError:
            bd = None
    cost = entitlements.token_map()["OWNCOST"]      # barrier-1 cost; env-overridable
    verdict = eligibility.can_render(
        account_present=account_present, dob_verified=dob_verified, birthdate=bd,
        today=date.today(), token_balance=token_balance, render_cost=cost,
        jurisdiction=jurisdiction or eligibility.M1_JURISDICTION,
        input_eligibility_passed=True,
    )
    if not verdict.allowed:
        analytics.render(spine, phase="requested", entry_point=ep, fail_reason=verdict.reason)
        raise HTTPException(403, {"reason": verdict.reason, "is_minor": verdict.is_minor})

    # 3) reserve tokens → render on Modal → commit on success / release on failure.
    remaining, hold = eligibility.place_hold(token_balance, cost)
    t0 = time.monotonic()
    try:
        png = render_client.render_tryon(await person.read(), await garment.read(), cloth_type)
        eligibility.commit_hold(hold)
    except Exception as e:
        eligibility.release_hold(remaining, hold)
        analytics.render(spine, phase="failed", entry_point=ep, fail_reason="render_error")
        raise HTTPException(502, f"render failed: {e}")

    elapsed = time.monotonic() - t0                  # wall-clock proxy until Modal reports GPU secs
    analytics.render(spine, phase="completed", entry_point=ep, source=authz.get("lane"),
                     gpu_seconds=round(elapsed, 2), latency_ms=int(elapsed * 1000))
    return Response(content=png, media_type="image/png")   # derive-and-discard: nothing stored


@app.post("/feedback")
def feedback_ep(payload: dict = Body(...), background: BackgroundTasks = None):
    """
    Live→sandbox→production loop's front door. A user (or an auto-assessment on the live
    app) reports a broken feature / misplaced button / crash; we normalize it into a
    deduped ticket, emit the analytics event, and hand back the routing decision.

    NOT a biometric ingestion (no photo, no measurement — just device/screen/note + recent
    event ids), so there is NO canRender gate: reporting a bug must never require an account
    or a verified DOB. The ticket routes device-specific *visual* bugs to the device farm;
    everything else goes the standard sandbox-debug path. Issue creation + the sandbox
    trigger live off-repo (see docs/FEEDBACK_LOOP.md); this endpoint produces the ticket
    they consume.
    """
    try:
        ticket = feedback_mod.build_ticket(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))

    spine = _spine(payload.get("session_id"), payload.get("user_id"), payload.get("guest_id"),
                   payload.get("surface"), payload.get("region"), payload.get("app_version"),
                   payload.get("device_os") or ticket.get("os"), None)
    analytics.feedback(spine, severity=ticket["severity"], route=ticket["route"],
                       kind=ticket["kind"], device_specific=ticket["device_specific"],
                       dedup_key=ticket["dedup_key"])
    # The analytics `feedback` event above carries only severity/route/kind. Emit the FULL
    # ticket (incl. the `note` body with the alpha user's flagged fields + comments) through
    # the SAME pluggable sink, so alpha feedback is actually collectable for rework — read it
    # from the logs, or point the sink at a store (see docs/alpha_hosting_guide.md).
    analytics.sink({"event": "feedback_ticket", "surface": spine.surface,
                    "user_id": spine.user_id, "guest_id": spine.guest_id, "ticket": ticket})
    # Email the ticket if a transport is configured. Sent SYNCHRONOUSLY (not a BackgroundTask):
    # a background send can be lost if the container restarts right after the response, and the
    # `emailed` flag then lies. Inline send is a ~1-2s HTTPS call (Resend), always logs its
    # result, and makes `emailed` reflect the ACTUAL outcome. Best-effort — never raises.
    emailed = notify.send_feedback_email(ticket) if notify.email_configured() else False
    # Durable, readable log: open a GitHub Issue per ticket when configured (survives the
    # ephemeral container + inbox; triageable in the repo). Best-effort, synchronous.
    logged = notify.create_feedback_issue(ticket) if notify.github_configured() else False
    return {"status": "queued", "ticket": ticket, "emailed": emailed, "logged": logged}


@app.post("/capture/instagram")
def capture_instagram_ep(payload: dict = Body(...)):
    """
    Instagram source: pull a Business/Creator account's images (Graph API) and run them
    through the SAME auto-picker as an upload set — owner found by face-dominance, everyone
    else discarded. Gated like every biometric ingestion; raw images discarded after.
    Requires the caller to supply a valid `access_token` + `ig_user_id` (you provision the
    Meta app + App Review); no credentials live in the code.
    """
    spine = _spine(payload.get("session_id"), payload.get("user_id"), payload.get("guest_id"),
                   payload.get("surface"), payload.get("region"), payload.get("app_version"),
                   payload.get("device_os"), None)
    gate = _biometric_gate(bool(payload.get("account_present")), bool(payload.get("dob_verified")),
                           payload.get("birthdate"), payload.get("jurisdiction"))
    analytics.eligibility(spine, allowed=gate.allowed, reason=gate.reason)
    if not gate.allowed:
        raise HTTPException(403, {"reason": gate.reason, "is_minor": gate.is_minor})

    ig_user_id, token = payload.get("ig_user_id"), payload.get("access_token")
    if not ig_user_id or not token:
        raise HTTPException(400, "need ig_user_id and access_token (Business/Creator + App Review)")

    from app import instagram_source as ig
    raws = ig.ingest_from_instagram(ig_user_id, token, ig.graph_media_fetcher,
                                    ig.http_downloader, limit=int(payload.get("limit", 50)))
    if not raws:
        return {"eligibility": {"passed": True, "reason": "ok"}, "decision": "retake_no_images",
                "source": "instagram", "n_sourced": 0}
    paths, d = _save_uploads(raws)
    try:
        from app import capture_session as cs
        result = cs.analyze_capture(paths)
    finally:
        _discard(paths, d)

    conf = (result.get("identity") or {}).get("overall")
    analytics.twin_extracted(spine, slice="capture", model="capture-aggregate-v0", confidence=conf)
    return {
        "eligibility": {"passed": True, "reason": "ok"},
        "source": "instagram", "n_sourced": len(raws),
        "decision": result["decision"], "identity": result["identity"],
        "timeline": result["timeline"], "appearance": result["appearance"],
        "n_faces_total": result["n_faces_total"], "n_user_faces": result["n_user_faces"],
    }
