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
import os
import uuid
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
import numpy as np

from datetime import date, datetime

from app import monk
from app import feedback as feedback_mod
from app.skin_tone import extract_skin_samples
from app import measurements as body
from app import face
from app import eligibility, style_profile, fit_score, entitlements
from app import store as store_mod
from app.body_models import assemble_body_models
from app.analytics import Analytics, Spine, ENTRY_POINTS as analytics_entry_points
from app.recognition import recognition_from_body_models

app = FastAPI(title="Krey Avatar — Service A (twin extraction)", version="0.5.0")

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


def _save_uploads(raws) -> list:
    """Write in-memory uploads to short-lived temp files (paths for the cv2 pipelines).
    The caller MUST delete them after processing — derive-and-discard: raw biometrics are
    never retained past the extraction that derives the compact record."""
    import tempfile
    paths = []
    d = tempfile.mkdtemp(prefix="krey-capture-")
    for i, raw in enumerate(raws):
        p = os.path.join(d, f"img_{i}.jpg")
        with open(p, "wb") as f:
            f.write(raw)
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
                                hair_features=hair_features)

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


@app.post("/feedback")
def feedback_ep(payload: dict = Body(...)):
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
    return {"status": "queued", "ticket": ticket}


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
