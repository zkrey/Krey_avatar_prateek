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
    render_live = vibe_live = banana_live = False
    try:
        from render import client as render_client
        render_live = render_client.render_configured()
        vibe_live = render_client.vibe_configured()
    except Exception:
        pass   # render/ package not on the image yet — never 500 the closet
    try:
        from render import banana as banana_mod
        banana_live = banana_mod.banana_configured()
    except Exception:
        pass
    return {
        "garments": catalog_mod.list_garments(cloth_type, segment),
        "source": "supabase" if catalog_mod.catalog_configured() else "sample",
        "segments": list(catalog_mod.SEGMENTS),
        "render_live": render_live,
        "vibe_live": vibe_live,
        "banana_live": banana_live,
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

def _normalize_upload(raw: bytes) -> bytes:
    """Apply EXIF orientation so phone photos are UPRIGHT before any CV/render step. Phones store
    rotation in EXIF metadata; cv2 and the diffusers pipelines decode raw pixels and ignore it, so
    a portrait selfie arrives sideways → the body parser can't find the torso → garbled render.
    Re-encode an upright JPEG. No-op on any failure."""
    try:
        import io as _io
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(_io.BytesIO(raw))).convert("RGB")
        buf = _io.BytesIO()
        im.save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception:
        return raw


@app.post("/closet/analyze")
async def closet_analyze(person: UploadFile = File(...)):
    """'Detect, don't demand': from the user's photo, return which cloth_types are renderable
    (upper/lower/overall) + an unlock hint. CPU pose only — no GPU, runs before any render."""
    from app import coverage as coverage_mod
    import numpy as np, cv2
    data = _normalize_upload(await person.read())
    if not data:
        raise HTTPException(400, "no image")
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not read image")
    return coverage_mod.analyze_coverage(img)


@app.get("/closet/render-check")
def closet_render_check():
    """Probe whether Service A can actually reach the Modal render endpoint (diagnostic).
    Hits Modal's /healthz and reports reachability + latency, without spending a GPU render."""
    import time
    import urllib.request
    url = os.environ.get("KREY_MODAL_RENDER_URL")
    if not url:
        return {"configured": False, "reachable": False, "detail": "KREY_MODAL_RENDER_URL not set"}
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/healthz", timeout=180) as r:
            body = r.read(200).decode("utf-8", "replace")
            return {"configured": True, "reachable": True, "status": r.status,
                    "ms": int((time.monotonic() - t0) * 1000), "body": body}
    except Exception as e:
        return {"configured": True, "reachable": False,
                "ms": int((time.monotonic() - t0) * 1000), "error": f"{type(e).__name__}: {e}"}


def _vibe_prompt(g: dict) -> tuple[str, str]:
    """Build an (prompt, negative) pair for the SDXL+InstantID "80s vibe" render from a garment's
    catalog metadata. The garment is described in words (InstantID generates the outfit/scene from
    text while keeping the person's identity) — aspirational, not exact-garment. Tuned to the retro
    studio-portrait trend: warm film look, recognisably the same person."""
    bits = [g.get("color"), g.get("subsegment") or g.get("category"), g.get("name")]
    garment = " ".join(str(b) for b in bits if b) or "a stylish outfit"
    # Identity + garment FIRST, 80s only as a light flavour. The earlier "glamorous fashion
    # editorial / feathered styling" hijacked the image into a stock fashion model, drowning out
    # both the person's face (InstantID) and the garment. Keep the subject = this exact person.
    prompt = (
        f"a realistic upper-body portrait photo of the same person, head and shoulders, "
        f"face large and centered in frame, clearly recognisable, "
        f"wearing {garment}, "
        "1980s retro vibe, warm film lighting, subtle vintage color grade, "
        "natural skin texture, sharp focus on the face, looking at camera, photorealistic, high detail"
    )
    negative = (
        "watermark, text, logo, signature, istock, getty, shutterstock, stock photo caption, username, "
        "different person, face swap, deformed face, distorted, disfigured, elongated neck, "
        "extra limbs, extra fingers, bad anatomy, blurry, low quality, cartoon, 3d render, plastic skin, "
        "feather boa, costume, over-styled"
    )
    return prompt, negative


def _skin_tone_clause(person_bytes: bytes) -> str:
    """Measure the person's skin tone (Monk scale + RGB) from their photo and return a prompt
    clause so the generative render synthesizes any NEWLY-EXPOSED skin (sleeveless/short garments)
    to match — instead of guessing. Reuses the existing skin_tone + monk pipeline. Degrades to ""
    on any failure (no face, deps missing) so it never blocks a render."""
    try:
        import cv2
        import numpy as np
        from app import monk, skin_tone
        bgr = cv2.imdecode(np.frombuffer(person_bytes, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            return ""
        res = skin_tone.extract_skin_samples(bgr)
        if not res.get("ok"):
            return ""
        rec = monk.classify(res["samples"])
        r, g, b = rec["rgb"]
        monkv = rec.get("monk_continuous") or rec.get("value")
        return (f" Keep the person's natural skin tone consistent on ALL skin, including any newly "
                f"exposed areas (arms, legs, midriff): approximately Monk scale {monkv}, "
                f"average RGB ({r},{g},{b}). Do not lighten, darken, or change their complexion.")
    except Exception:
        return ""


def _banana_prompt(g: dict, style: str = "studio") -> str:
    """Instruction for Nano Banana (Gemini). It receives the person image (1st) and the garment
    image (2nd), so we ask it to dress the SAME person in the ACTUAL garment shown — real garment,
    real identity. `style` picks the aesthetic:
      - "studio"  : clean, faithful, flattering editorial portrait (the default Studio look).
      - "eighties": the 80s trend — strong 1980s retro-portrait styling, still the same person and
        the actual garment (this replaces the old SDXL+InstantID vibe path, which used the garment
        as text only and lost identity)."""
    name = g.get("name") or "the outfit"
    base = (
        "Using the first image as the person and the second image as the garment, generate a "
        f"photorealistic image of the SAME person — keep their face and identity exactly — now "
        f"wearing the garment from the second image ({name}). Fit the garment naturally to their "
        "body and pose. " + _GENDER_GUARD
    )
    if style == "eighties":
        look = (
            "Style it as a bold 1980s retro studio portrait: warm film lighting with a soft glow, "
            "vintage color grade and gentle film grain, feathered-light rim highlights, and a clean "
            "retro studio backdrop (soft gradient or muted pastel). Keep the EXACT garment from the "
            "second image — do not restyle or replace it. "
        )
    else:
        look = (
            "Keep it a clean, flattering editorial portrait: natural lighting, true-to-life colour, "
            "a simple uncluttered background. "
        )
    return base + look + "Keep it realistic and tasteful, no text or watermarks."


# Gender guardrail — Nano otherwise defaulted to WOMENSWEAR on the no-garment trend path (a man
# got a gown / lehenga). This line is added to EVERY render prompt so the person's apparent gender
# presentation is preserved unless the user explicitly picks otherwise.
_GENDER_GUARD = (
    "Preserve the person's apparent gender presentation exactly as in the photo — do NOT feminize "
    "or masculinize them, and choose garments appropriate to that presentation. "
)

# --- Style trends: iconic-look presets applied to the user's OWN photo via Nano, no garment and
# no manual catalog adds. Each is an openly-known fashion aesthetic/era (NOT a real person) — the
# render always keeps the USER's face/identity, so we never generate a celebrity's likeness. Each
# trend carries a feminine (fem) and masculine (masc) garment variant so a man isn't dressed in a
# gown; the variant is chosen by the gender hint, else by the person's presentation in the photo.
# Add new trends here; the UI reads them from /closet/trends. -------------------------------------
_STYLE_TRENDS: dict[str, dict] = {
    # --- Luxe / status ---
    "oldhollywood": {"label": "Old Hollywood", "emoji": "🎞️", "group": "Luxe",
        "fem": "a glamorous bias-cut satin gown with soft finger-wave hair, pearls and a red lip",
        "masc": "a sharply tailored black tuxedo with a bow tie and slicked-back hair",
        "look": "warm cinematic studio lighting with a soft vignette, old-Hollywood elegance"},
    "oldmoney": {"label": "Old Money", "emoji": "🥂", "group": "Luxe",
        "fem": "an understated old-money look — a cashmere knit, tailored trousers and pearls, no logos",
        "masc": "an old-money look — a navy blazer, oxford shirt, chinos and loafers, no logos",
        "look": "heritage-wealth ease, muted neutral palette"},
    "quietluxury": {"label": "Quiet Luxury", "emoji": "🤎", "group": "Luxe",
        "fem": "quiet-luxury tailoring — an impeccably cut neutral coat over a fine knit, no branding",
        "masc": "quiet-luxury tailoring — a beautifully cut overcoat over a cashmere crewneck, no branding",
        "look": "understated, exquisite fabric, zero logos"},
    "mobwife": {"label": "Mob Wife", "emoji": "🧥", "group": "Luxe",
        "fem": "an oversized faux-fur coat, bold gold jewelry, dark sunglasses and a sleek blowout",
        "masc": "a sharp dark overcoat over a shirt with bold gold accents and slicked-back hair",
        "look": "moody high-contrast glamour"},
    # --- Clean & soft ---
    "cleangirl": {"label": "Clean Look", "emoji": "🤍", "group": "Clean & Soft",
        "fem": "a minimalist 'clean girl' look — a slicked-back low bun, gold hoops and a neutral tailored set",
        "masc": "a clean minimalist look — a fitted neutral tee or fine knit with tailored trousers, groomed",
        "look": "soft natural daylight, fresh and polished"},
    "coastalgrandma": {"label": "Coastal", "emoji": "🧺", "group": "Clean & Soft",
        "fem": "a coastal look — breezy linen trousers, an oversized knit and a flowy blouse",
        "masc": "a coastal look — relaxed linen trousers, an open linen shirt and a light knit",
        "look": "breezy seaside ease, soft daylight"},
    "balletcore": {"label": "Balletcore", "emoji": "🩰", "group": "Clean & Soft",
        "fem": "a balletcore look — a wrap cardigan with ribbon details and a tulle or satin skirt, soft bun",
        "masc": "a soft minimalist look — a fine knit with tailored trousers and clean lines",
        "look": "pale, delicate, off-duty softness"},
    "cottagecore": {"label": "Cottagecore", "emoji": "🌸", "group": "Clean & Soft",
        "fem": "a cottagecore look — a floral prairie dress with a pinafore and loose waves",
        "masc": "a cottagecore look — a linen shirt with suspenders and rolled trousers",
        "look": "pastoral warmth, soft natural light"},
    # --- Street ---
    "streetwear": {"label": "Streetwear", "emoji": "🧢", "group": "Street",
        "fem": "an oversized hoodie or bomber with cargo trousers and fresh sneakers",
        "masc": "an oversized hoodie or bomber with cargo trousers and fresh sneakers",
        "look": "crisp urban backdrop, confident casual stance"},
    "gorpcore": {"label": "Gorpcore", "emoji": "🥾", "group": "Street",
        "fem": "a gorpcore outdoor look — a technical shell or fleece with cargo trousers and trail sneakers",
        "masc": "a gorpcore outdoor look — a technical shell or fleece with cargo trousers and trail sneakers",
        "look": "crisp outdoorsy utility"},
    "techwear": {"label": "Techwear", "emoji": "🖤", "group": "Street",
        "fem": "a techwear look — an all-black waterproof shell with tactical straps and cargo pockets",
        "masc": "a techwear look — an all-black waterproof shell with tactical straps and cargo pockets",
        "look": "moody futuristic urban"},
    "y2kpop": {"label": "Y2K Pop", "emoji": "💿", "group": "Street",
        "fem": "an early-2000s Y2K outfit — a metallic or denim mini with a cropped top, tinted sunglasses and butterfly clips",
        "masc": "an early-2000s Y2K streetwear look — a baggy denim or tracksuit with a chain, tinted sunglasses and a bucket hat",
        "look": "flash-lit party energy with playful saturated colour"},
    # --- Edge / era ---
    "grunge": {"label": "Grunge", "emoji": "🎸", "group": "Edge & Era",
        "fem": "a 90s grunge look — a plaid flannel over a band tee with ripped jeans and boots",
        "masc": "a 90s grunge look — a plaid flannel over a band tee with ripped jeans and boots",
        "look": "moody, overcast, lived-in"},
    "darkacademia": {"label": "Dark Academia", "emoji": "📚", "group": "Edge & Era",
        "fem": "a dark-academia look — a tweed blazer, turtleneck and pleated skirt with a leather satchel",
        "masc": "a dark-academia look — a tweed blazer, turtleneck and trousers with a leather satchel",
        "look": "moody library warmth, autumnal"},
    "ninetiesminimal": {"label": "90s Minimal", "emoji": "⬛", "group": "Edge & Era",
        "fem": "a sleek 1990s minimalist slip dress with delicate jewelry and straight sleek hair",
        "masc": "a 1990s minimalist look — a crisp monochrome shirt or fine knit with straight-leg trousers",
        "look": "matte true-to-life colour, clean uncluttered backdrop"},
    "regencycore": {"label": "Regency", "emoji": "🎻", "group": "Edge & Era",
        "fem": "a Regency-inspired look — an empire-waist gown with pearls and romantic florals",
        "masc": "a Regency-inspired look — a tailored tailcoat with a cravat and waistcoat",
        "look": "romantic period elegance"},
    "cowboycore": {"label": "Western", "emoji": "🤠", "group": "Edge & Era",
        "fem": "a cowgirl look — denim with a fringe jacket, a cowboy hat and boots",
        "masc": "a western look — denim with a fringe or suede jacket, a cowboy hat and boots",
        "look": "sun-drenched country warmth"},
    # --- Glam & pro ---
    "corporatesiren": {"label": "Corporate", "emoji": "💼", "group": "Glam & Pro",
        "fem": "a corporate-siren look — a sharp blazer, pencil skirt and heels with sleek hair",
        "masc": "a power-tailored look — a sharp suit with a crisp shirt, polished",
        "look": "boardroom power, confident"},
    "italiansummer": {"label": "Italian Summer", "emoji": "🍅", "group": "Glam & Pro",
        "fem": "an Italian-summer look — a red or terracotta linen sundress with a straw hat and gold jewelry",
        "masc": "an Italian-summer look — an open linen shirt in warm tones with tailored shorts and loafers",
        "look": "sun-drenched Mediterranean warmth"},
    "bohofestival": {"label": "Boho Festival", "emoji": "🌾", "group": "Glam & Pro",
        "fem": "a flowy printed maxi with fringe and layered necklaces, loose waves",
        "masc": "a relaxed open linen or printed shirt with layered beaded necklaces and tousled hair",
        "look": "warm golden-hour light with a soft open-air backdrop"},
    # --- Indian — heritage ---
    "kanjeevaram": {"label": "Kanjeevaram", "emoji": "🪔", "group": "Indian Heritage",
        "fem": "a lustrous Kanjeevaram-style silk saree with a contrast zari border and temple-gold jewelry",
        "masc": "a fine silk kurta with a zari-bordered silk angavastram (stole) and a veshti",
        "look": "warm festive South-Indian elegance"},
    "banarasi": {"label": "Banarasi", "emoji": "✨", "group": "Indian Heritage",
        "fem": "a rich Banarasi-style silk saree with intricate gold brocade and heirloom jewelry",
        "masc": "a regal silk kurta-churidar with a gold-brocade nehru jacket",
        "look": "opulent North-Indian bridal warmth"},
    "bandhani": {"label": "Bandhani", "emoji": "🪞", "group": "Indian Heritage",
        "fem": "a vibrant bandhani tie-dye chaniya choli with mirror-work and oxidised jewelry",
        "masc": "a bandhani-print kurta with a mirror-work jacket",
        "look": "festive Navratri energy, bright and celebratory"},
    "kasavu": {"label": "Kerala Kasavu", "emoji": "🌼", "group": "Indian Heritage",
        "fem": "a white-and-gold Kerala kasavu saree with jasmine in the hair and gold jewelry",
        "masc": "a white-and-gold kasavu mundu with a matching angavastram",
        "look": "serene Onam elegance, cream and gold"},
    # --- Indian — occasion ---
    "royallehenga": {"label": "Royal Lehenga", "emoji": "👑", "group": "Indian Occasion",
        "fem": "an opulent embroidered bridal lehenga with heavy zardozi, a dupatta and statement jewelry",
        "masc": "a richly embroidered sherwani with a brooch, churidar and a stole",
        "look": "grand wedding-couture opulence"},
    "sherwani": {"label": "Sherwani", "emoji": "🤵", "group": "Indian Occasion",
        "fem": "an embroidered sherwani-inspired jacket over a flowing dress or palazzo",
        "masc": "a classic embroidered sherwani with churidar, a brooch and a stole",
        "look": "regal groom elegance"},
    "anarkali": {"label": "Anarkali", "emoji": "💃", "group": "Indian Occasion",
        "fem": "a flowing floor-length Anarkali suit with delicate embroidery and a dupatta",
        "masc": "a long embroidered angrakha-style kurta with churidar",
        "look": "graceful festive elegance"},
    "chikankari": {"label": "Chikankari", "emoji": "🧵", "group": "Indian Occasion",
        "fem": "a delicate white chikankari-embroidered kurta with pastel palazzos",
        "masc": "a crisp white chikankari-embroidered kurta with a nehru jacket",
        "look": "soft Lucknowi refinement, white-on-white"},
    "indowestern": {"label": "Indo-Western", "emoji": "👖", "group": "Indian Occasion",
        "fem": "an Indo-Western co-ord — an embroidered kurta with tailored palazzos or a cape and modern jewelry",
        "masc": "an Indo-Western look — a bandhgala jacket over a tee with tailored trousers",
        "look": "modern metro fusion, culturally rooted"},
}


def _trend_prompt(trend_key: str, gender: str = "auto") -> str:
    """Instruction for a style-trend render: Nano receives ONLY the person image and restyles the
    SAME person into the chosen iconic aesthetic. No garment image, no impersonation — the user's
    own face/identity AND gender presentation are preserved; only the styling changes. `gender`
    (woman|man|neutral|auto) picks the garment variant; 'auto' asks Nano to match the photo."""
    t = _STYLE_TRENDS.get(trend_key) or {}
    fem = t.get("fem") or t.get("clause") or "a polished, flattering editorial outfit"
    masc = t.get("masc") or fem
    look = t.get("look") or ""
    g = (gender or "auto").strip().lower()
    if g in ("woman", "women", "female", "f", "she"):
        outfit = fem
    elif g in ("man", "men", "male", "m", "he"):
        outfit = masc
    else:  # neutral / auto — let the photo decide, but never default to womenswear
        outfit = (f"attire matching the person's own gender presentation in the photo — if they "
                  f"present feminine: {fem}; if they present masculine: {masc}")
    tail = (" " + look + ".") if look else ""
    return (
        "Using the image as the person, generate a photorealistic portrait of the SAME person — "
        "keep their face, identity and body exactly. " + _GENDER_GUARD +
        "Style them in " + outfit + "." + tail +
        " Flattering and realistic, head to mid-body. Do not change their face or make them look "
        "like someone else. No text or watermarks."
    )


@app.get("/closet/trends")
def closet_trends():
    """The style-trend gallery (iconic-look presets). Only meaningful when Nano is live, since the
    trends render through it. Returns [{key,label,emoji}] in display order."""
    from render import banana as banana_mod
    live = banana_mod.banana_configured()
    return {"live": live,
            "trends": [{"key": k, "label": v["label"], "emoji": v.get("emoji", "✨"),
                        "group": v.get("group", "Trends")}
                       for k, v in _STYLE_TRENDS.items()]}


@app.post("/closet/trend")
async def closet_trend(trend: str = Form(...), owner_hint: str = Form(...),
                       person: UploadFile = File(...), gender: str = Form("auto")):
    """Render the user's own photo into an iconic style trend via Nano (no garment). Synchronous —
    returns the finished look directly, which the client can add to the ranking tray like any look.
    `gender` (woman|man|neutral|auto) keeps a man from being dressed in womenswear (guardrail)."""
    from app import catalog as catalog_mod
    from render import banana as banana_mod
    from starlette.concurrency import run_in_threadpool
    if trend not in _STYLE_TRENDS:
        raise HTTPException(400, "unknown trend")
    if not banana_mod.banana_configured():
        raise HTTPException(503, "trend backend not configured (set GEMINI_API_KEY)")
    person_bytes = _normalize_upload(await person.read())
    if not person_bytes:
        raise HTTPException(400, "missing person image")
    prompt = _trend_prompt(trend, gender) + await run_in_threadpool(_skin_tone_clause, person_bytes)
    try:
        png = await run_in_threadpool(banana_mod.generate, person_bytes, None, prompt)
    except Exception as e:
        raise HTTPException(502, f"render failed: {e}")
    url = catalog_mod.upload_image(png, content_type="image/png", ext="png")
    label = _STYLE_TRENDS[trend]["label"]
    look_id = catalog_mod.create_look(owner_hint=owner_hint, name=f"{label} trend", image_url=url)
    return {"look_id": look_id, "image_url": url,
            "look_url": f"/look/{look_id}" if look_id else None, "mode": "trend",
            "trend": trend, "done": True}


@app.post("/closet/tryon")
async def closet_tryon(garment_id: str = Form(...), owner_hint: str = Form(...),
                       person: UploadFile = File(...), mode: str = Form("catvton")):
    """Fire-and-poll try-on: SPAWN the render on Modal and return a job_id immediately (the request
    stays short — no Railway 5-min timeout). The client then polls /closet/tryon/result.
    mode: 'catvton' (faithful-garment 2D try-on) or 'vibe' (SDXL+InstantID aspirational 80s render)."""
    from app import catalog as catalog_mod
    from render import client as render_client
    from starlette.concurrency import run_in_threadpool
    g = catalog_mod.get_garment(garment_id)
    if not g:
        raise HTTPException(404, "garment not found")
    person_bytes = _normalize_upload(await person.read())
    if not person_bytes:
        raise HTTPException(400, "missing person image")

    if mode in ("banana", "banana80s"):
        # Nano Banana / Gemini: person + garment images -> one composed image, synchronously
        # (fast enough to finish inside the request). Returns the finished look directly.
        # "banana80s" is the 80s trend routed through Nano (same engine, stronger retro styling).
        from render import banana as banana_mod
        if not banana_mod.banana_configured():
            raise HTTPException(503, "nano-banana backend not configured (set GEMINI_API_KEY)")
        style = "eighties" if mode == "banana80s" else "studio"
        garment_bytes = catalog_mod.fetch_bytes(g.get("image_url"))
        prompt = _banana_prompt(g, style) + await run_in_threadpool(_skin_tone_clause, person_bytes)
        try:
            png = await run_in_threadpool(banana_mod.generate, person_bytes, garment_bytes, prompt)
        except Exception as e:
            raise HTTPException(502, f"render failed: {e}")
        url = catalog_mod.upload_image(png, content_type="image/png", ext="png")
        look_id = catalog_mod.create_look(owner_hint=owner_hint, name=g.get("name"), image_url=url,
                                          segment=g.get("segment"), subsegment=g.get("subsegment"))
        return {"look_id": look_id, "image_url": url,
                "look_url": f"/look/{look_id}" if look_id else None, "mode": mode, "done": True}

    if mode == "vibe":
        if not render_client.vibe_configured():
            raise HTTPException(503, "vibe render backend not live yet")
        prompt, negative = _vibe_prompt(g)
        prompt += await run_in_threadpool(_skin_tone_clause, person_bytes)
        try:
            call_id = await run_in_threadpool(render_client.vibe_spawn, person_bytes, prompt, negative)
        except Exception as e:
            raise HTTPException(502, f"could not start render: {e}")
        return {"job_id": call_id, "mode": "vibe"}

    if not render_client.render_configured():
        raise HTTPException(503, "render backend not live yet")
    garment_bytes = catalog_mod.fetch_bytes(g.get("image_url"))
    if not garment_bytes:
        raise HTTPException(400, "missing garment image")
    cloth_type = g.get("cloth_type") if g.get("cloth_type") in ("upper", "lower", "overall") else "upper"
    try:
        call_id = await run_in_threadpool(render_client.render_spawn, person_bytes, garment_bytes, cloth_type)
    except Exception as e:
        raise HTTPException(502, f"could not start render: {e}")
    return {"job_id": call_id, "mode": "catvton"}


@app.get("/closet/tryon/result")
async def closet_tryon_result(job_id: str, garment_id: str, owner_hint: str = "anon",
                              mode: str = "catvton"):
    """Poll a spawned render. 202 {status:pending} while the GPU works; when ready, store the PNG
    as a shareable look and return its url. Each call is short → survives Railway/Modal timeouts."""
    from app import catalog as catalog_mod
    from render import client as render_client
    from starlette.concurrency import run_in_threadpool
    poll = render_client.vibe_poll if mode == "vibe" else render_client.render_poll
    try:
        png = await run_in_threadpool(poll, job_id)
    except Exception as e:
        raise HTTPException(502, f"render failed: {e}")
    if png is None:
        return Response(status_code=202, content='{"status":"pending"}', media_type="application/json")
    g = catalog_mod.get_garment(garment_id) or {}
    url = catalog_mod.upload_image(png, content_type="image/png", ext="png")
    look_id = catalog_mod.create_look(owner_hint=owner_hint, name=g.get("name"), image_url=url,
                                      segment=g.get("segment"), subsegment=g.get("subsegment"))
    return {"look_id": look_id, "image_url": url, "look_url": f"/look/{look_id}" if look_id else None}


@app.post("/closet/ballot")
def closet_ballot(payload: dict = Body(...)):
    """Bundle 2+ rendered try-on looks into a ballot so friends can rank which garment suits you
    best. Reuses the rank engine — the generative try-ons become the ballot's looks."""
    from app import catalog as catalog_mod
    look_ids = [str(x) for x in (payload.get("look_ids") or []) if x][:5]
    if len(look_ids) < 2:
        raise HTTPException(400, "need at least 2 looks to rank")
    owner = str(payload.get("owner_hint") or "anon")
    set_id = catalog_mod.create_rank_set(owner_hint=owner, look_ids=look_ids,
                                         name=payload.get("name"), ref=owner)
    if not set_id:
        raise HTTPException(502, "could not create the ballot")
    return {"set_id": set_id, "rank_url": f"/rank/{set_id}"}


@app.post("/closet/confidence")
def closet_confidence(payload: dict = Body(...)):
    """One-tap 'how confident do you feel in this?' (1–10) on the render-done overlay — the PRE
    (pre-crowd) self-confidence the closet flow was missing. Writes confidence_marks(phase='pre')
    so the /admin confidence-lift (Δ post-pre) and self↔crowd Kendall-τ have a baseline for
    closet-made looks. Best-effort."""
    from app import catalog as catalog_mod
    ok = catalog_mod.record_confidence(
        set_id=payload.get("set_id"), look_id=payload.get("look_id"),
        owner_hint=payload.get("owner_hint"), phase="pre", value=payload.get("value"))
    return {"ok": bool(ok)}


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


@app.get("/health/cycle")
def health_cycle(token: Optional[str] = None):
    """One-URL probe of the whole share→rank→referral loop, so the cycle can be verified without
    opening Supabase. Admin-gated (?token=KREY_ADMIN_TOKEN). Does a real rank_votes round-trip
    (insert then read-back under a throwaway set_id) to DEFINITIVELY detect the 'public read votes'
    RLS policy — the one gap that makes voting record fine but results read 0."""
    from app import catalog as catalog_mod
    from render import client as render_client
    from render import banana as banana_mod
    if not _admin_authed(token):
        raise HTTPException(401, "add ?token=YOUR_ADMIN_TOKEN")

    out: dict = {"supabase_configured": catalog_mod.catalog_configured(),
                 "render": {"catvton": render_client.render_configured(),
                            "banana": banana_mod.banana_configured(),
                            "vibe": render_client.vibe_configured()}}

    def read_probe(path: str) -> dict:
        r = catalog_mod._get(path)
        return {"reachable": r is not None, "rows_visible": (len(r) if isinstance(r, list) else None)}

    out["reads"] = {
        "garments": read_probe("garments?select=garment_id&limit=1"),
        "looks": read_probe("looks?select=look_id&limit=1"),
        "rank_sets": read_probe("rank_sets?select=set_id&limit=1"),
        "referrals": read_probe("referrals?select=referrer_hint&limit=1"),
        "confidence_marks": read_probe("confidence_marks?select=phase&limit=1"),
    }

    # rank_votes round-trip: insert a throwaway vote, then read it back. If insert works but the
    # read returns nothing, the SELECT ('public read votes') policy is missing.
    hc = "__healthcheck__"
    ins = catalog_mod.record_vote(set_id=hc, winner_look_id="__hc_w__",
                                  loser_look_id="__hc_l__", voter_hint="healthprobe")
    back = catalog_mod._get(f"rank_votes?set_id=eq.{hc}&select=winner_look_id&limit=1")
    select_ok = bool(back)
    out["rank_votes"] = {
        "insert_ok": bool(ins), "select_ok": select_ok,
        "policy_ok": bool(ins) and select_ok,
        "fix": None if (bool(ins) and select_ok) else
               "In Supabase SQL: create policy \"public read votes\" on rank_votes for select using (true);",
    }

    reads_ok = all(v["reachable"] for v in out["reads"].values())
    out["loop_ok"] = bool(out["supabase_configured"] and reads_ok and out["rank_votes"]["policy_ok"]
                          and out["render"]["banana"])
    return out


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
