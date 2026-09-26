"""
Garment catalog — the try-on "supply" side.

Reads garments from Supabase (PostgREST) when configured via KREY_SUPABASE_URL +
KREY_SUPABASE_KEY; otherwise falls back to a small built-in sample so /closet renders with
zero setup. Pure stdlib (urllib), same discipline as app/notify.py — no new dependency on the
FastAPI service.

Schema (see docs/catalog_schema.sql): a `garments` row is
    {garment_id, name, cloth_type, category, color, image_url, source}
where cloth_type ∈ {upper, lower, overall} — the one field the render actually needs. The rest
is for display + filtering. Bulk-loaded by bench/ingest_garments.py.
"""
from __future__ import annotations
import json
import os
import urllib.request

CLOTH_TYPES = ("upper", "lower", "overall")

# Built-in sample so the browse UI works before any dataset/Supabase is wired. No image files
# (image_url=None) — the UI draws a colour tile — so nothing bloats the repo.
_SAMPLE = [
    {"garment_id": "s01", "name": "White Tee", "cloth_type": "upper", "category": "tee", "color": "#efeee8", "image_url": None, "source": "sample"},
    {"garment_id": "s02", "name": "Black Tank", "cloth_type": "upper", "category": "tank", "color": "#22242a", "image_url": None, "source": "sample"},
    {"garment_id": "s03", "name": "Blue Oxford Shirt", "cloth_type": "upper", "category": "shirt", "color": "#3f6fb0", "image_url": None, "source": "sample"},
    {"garment_id": "s04", "name": "Olive Kurta", "cloth_type": "upper", "category": "kurta", "color": "#6b6a3a", "image_url": None, "source": "sample"},
    {"garment_id": "s05", "name": "Red Crop Top", "cloth_type": "upper", "category": "top", "color": "#b0303a", "image_url": None, "source": "sample"},
    {"garment_id": "s06", "name": "Beige Chinos", "cloth_type": "lower", "category": "trousers", "color": "#cbb894", "image_url": None, "source": "sample"},
    {"garment_id": "s07", "name": "Indigo Jeans", "cloth_type": "lower", "category": "jeans", "color": "#33415c", "image_url": None, "source": "sample"},
    {"garment_id": "s08", "name": "Black Skirt", "cloth_type": "lower", "category": "skirt", "color": "#1e1f24", "image_url": None, "source": "sample"},
    {"garment_id": "s09", "name": "Floral Dress", "cloth_type": "overall", "category": "dress", "color": "#c76b8e", "image_url": None, "source": "sample"},
    {"garment_id": "s10", "name": "Blue Anarkali", "cloth_type": "overall", "category": "dress", "color": "#2aa7c4", "image_url": None, "source": "sample"},
    {"garment_id": "s11", "name": "Green Jumpsuit", "cloth_type": "overall", "category": "jumpsuit", "color": "#2e7d5b", "image_url": None, "source": "sample"},
    {"garment_id": "s12", "name": "Grey Hoodie", "cloth_type": "upper", "category": "hoodie", "color": "#8a8d93", "image_url": None, "source": "sample"},
]


def catalog_configured() -> bool:
    """True when a Supabase catalog is wired; otherwise the sample set is served."""
    return bool(os.environ.get("KREY_SUPABASE_URL") and os.environ.get("KREY_SUPABASE_KEY"))


def list_garments(cloth_type: str | None = None, limit: int = 200) -> list[dict]:
    """Garments for the closet, optionally filtered by cloth_type. Falls back to the sample set
    (or on any Supabase error) so the page never hard-fails."""
    if catalog_configured():
        try:
            return _from_supabase(cloth_type, limit)
        except Exception:
            pass  # fall through to sample rather than 500 the closet
    rows = [g for g in _SAMPLE if not cloth_type or g["cloth_type"] == cloth_type]
    return rows[:limit]


def _from_supabase(cloth_type: str | None, limit: int) -> list[dict]:
    base = os.environ["KREY_SUPABASE_URL"].rstrip("/")
    key = os.environ["KREY_SUPABASE_KEY"]
    url = f"{base}/rest/v1/garments?select=garment_id,name,cloth_type,category,color,image_url,source&limit={int(limit)}"
    if cloth_type in CLOTH_TYPES:
        url += f"&cloth_type=eq.{cloth_type}"
    req = urllib.request.Request(url)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())
