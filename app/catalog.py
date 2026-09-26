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
import secrets
import urllib.parse
import urllib.request

CLOTH_TYPES = ("upper", "lower", "overall")
# ANALYTICS dimension (distinct from cloth_type, which the render needs). Thesis: which of
# these gets shared most? Populated by bench/ingest_garments.py from the dataset metadata.
SEGMENTS = ("intimate", "wedding", "ethnic", "formal", "party", "athleisure", "casual")
EVENT_TYPES = ("view", "try", "share")

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


def list_garments(cloth_type: str | None = None, segment: str | None = None,
                   limit: int = 200) -> list[dict]:
    """Garments for the closet, optionally filtered by cloth_type and/or segment. Falls back to
    the sample set (or on any Supabase error) so the page never hard-fails."""
    if catalog_configured():
        try:
            return _from_supabase(cloth_type, segment, limit)
        except Exception:
            pass  # fall through to sample rather than 500 the closet
    rows = [g for g in _SAMPLE
            if (not cloth_type or g["cloth_type"] == cloth_type)
            and (not segment or g.get("segment") == segment)]
    return rows[:limit]


def _from_supabase(cloth_type: str | None, segment: str | None, limit: int) -> list[dict]:
    base = os.environ["KREY_SUPABASE_URL"].rstrip("/")
    key = os.environ["KREY_SUPABASE_KEY"]
    url = (f"{base}/rest/v1/garments"
           f"?select=garment_id,name,cloth_type,segment,subsegment,category,color,image_url,source"
           f"&limit={int(limit)}")
    if cloth_type in CLOTH_TYPES:
        url += f"&cloth_type=eq.{cloth_type}"
    if segment in SEGMENTS:
        url += f"&segment=eq.{segment}"
    req = urllib.request.Request(url)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _sb():
    """(base, key) for the anon Supabase API, or None when not configured."""
    if not catalog_configured():
        return None
    return os.environ["KREY_SUPABASE_URL"].rstrip("/"), os.environ["KREY_SUPABASE_KEY"]


def _post(path: str, rows: list[dict], timeout: int = 10) -> bool:
    """Best-effort insert into a Supabase table via the anon key. Never raises."""
    sb = _sb()
    if not sb:
        return False
    base, key = sb
    req = urllib.request.Request(f"{base}/rest/v1/{path}",
                                 data=json.dumps(rows).encode(), method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=minimal")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status in (200, 201, 204)
    except Exception:
        return False


def _get(path: str, timeout: int = 15):
    """Best-effort read from Supabase via the anon key. Returns parsed JSON or None."""
    sb = _sb()
    if not sb:
        return None
    base, key = sb
    req = urllib.request.Request(f"{base}/rest/v1/{path}")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def log_event(garment_id: str, event_type: str, segment: str | None = None,
              cloth_type: str | None = None, session_hint: str | None = None,
              channel: str | None = None, referrer_hint: str | None = None) -> bool:
    """Record a view/try/share against a garment (the 'what gets shared most' thesis).

    Writes to the durable Supabase `garment_events` table via the anon key (insert-only RLS).
    Best-effort: returns False and never raises, so a logging hiccup never breaks the UI.
    """
    if event_type not in EVENT_TYPES or not garment_id:
        return False
    return _post("garment_events", [{
        "garment_id": str(garment_id)[:128],
        "event_type": event_type,
        "segment": segment if segment in SEGMENTS else None,
        "cloth_type": cloth_type if cloth_type in CLOTH_TYPES else None,
        "session_hint": (str(session_hint)[:64] if session_hint else None),
        "channel": (str(channel)[:32] if channel else None),
        "referrer_hint": (str(referrer_hint)[:64] if referrer_hint else None),
    }])


# --- the share -> rank -> confidence -> referral loop (social-testing experiment) ---

def get_look(look_id: str) -> dict | None:
    """One rendered look for the /look/<id> share page."""
    rows = _get(f"looks?look_id=eq.{urllib.parse.quote(str(look_id))}&limit=1")
    return rows[0] if rows else None


def get_rank_set(set_id: str) -> dict | None:
    """A ballot (rank_set) plus its looks, for the /rank/<id> voting page."""
    rows = _get(f"rank_sets?set_id=eq.{urllib.parse.quote(str(set_id))}&limit=1")
    if not rows:
        return None
    rs = rows[0]
    ids = rs.get("look_ids") or []
    if isinstance(ids, str):
        try:
            ids = json.loads(ids)
        except Exception:
            ids = []
    looks = []
    if ids:
        inlist = ",".join(urllib.parse.quote(str(i)) for i in ids)
        looks = _get(f"looks?look_id=in.({inlist})") or []
        order = {str(i): n for n, i in enumerate(ids)}
        looks.sort(key=lambda l: order.get(str(l.get("look_id")), 99))
    rs["looks"] = looks
    return rs


def record_vote(set_id: str, winner_look_id: str, loser_look_id: str | None = None,
                voter_hint: str | None = None, referrer_hint: str | None = None) -> bool:
    """One pairwise vote on a ballot (anonymous — no signup)."""
    if not winner_look_id:
        return False
    return _post("rank_votes", [{
        "set_id": str(set_id)[:64] if set_id else None,
        "winner_look_id": str(winner_look_id)[:64],
        "loser_look_id": str(loser_look_id)[:64] if loser_look_id else None,
        "voter_hint": str(voter_hint)[:64] if voter_hint else None,
        "referrer_hint": str(referrer_hint)[:64] if referrer_hint else None,
    }])


def record_referral(referrer_hint: str, visitor_hint: str | None = None,
                    source: str | None = None, activated: bool = False) -> bool:
    """The network-effect edge: a visitor arrived via someone's share link (source=look/rank/closet),
    and whether they activated (built their own fit). Feeds the K-factor rollup."""
    if not referrer_hint:
        return False
    return _post("referrals", [{
        "referrer_hint": str(referrer_hint)[:64],
        "visitor_hint": str(visitor_hint)[:64] if visitor_hint else None,
        "source": str(source)[:16] if source else None,
        "activated": bool(activated),
    }])


# --- self-serve creation: upload your own outfit photos, bundle a ballot, share (no render needed) ---
LOOKS_BUCKET = os.environ.get("KREY_LOOKS_BUCKET", "looks")


def upload_image(data: bytes, content_type: str = "image/jpeg", ext: str = "jpg") -> str | None:
    """Upload a user outfit photo to the public `looks` Storage bucket. Returns its public URL.

    Needs a PUBLIC bucket named `looks` with an anon-insert Storage policy (docs/catalog_schema.sql).
    Best-effort: returns None on any failure so the flow degrades instead of 500-ing.
    """
    sb = _sb()
    if not sb or not data:
        return None
    base, key = sb
    name = f"{secrets.token_urlsafe(8)}.{ext}"
    url = f"{base}/storage/v1/object/{LOOKS_BUCKET}/{name}"
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", content_type)
    req.add_header("x-upsert", "true")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status in (200, 201):
                return f"{base}/storage/v1/object/public/{LOOKS_BUCKET}/{name}"
    except Exception:
        pass
    return None


def create_look(owner_hint: str, name: str | None, image_url: str | None,
                confidence_self: int | None = None, is_baseline: bool = False,
                segment: str | None = None, subsegment: str | None = None) -> str | None:
    """Insert a look row; returns its short look_id slug."""
    look_id = secrets.token_urlsafe(7)
    ok = _post("looks", [{
        "look_id": look_id,
        "owner_hint": str(owner_hint)[:64] if owner_hint else None,
        "name": str(name)[:120] if name else None,
        "image_url": image_url,
        "confidence_self": int(confidence_self) if confidence_self is not None else None,
        "is_baseline": bool(is_baseline),
        "segment": segment if segment in SEGMENTS else None,
        "subsegment": str(subsegment)[:48] if subsegment else None,
    }])
    return look_id if ok else None


def create_rank_set(owner_hint: str, look_ids: list[str], name: str | None = None,
                    ref: str | None = None) -> str | None:
    """Bundle looks into a ballot; returns its short set_id slug."""
    if not look_ids:
        return None
    set_id = secrets.token_urlsafe(7)
    ok = _post("rank_sets", [{
        "set_id": set_id,
        "owner_hint": str(owner_hint)[:64] if owner_hint else None,
        "look_ids": [str(i)[:64] for i in look_ids],
        "ref": str(ref or owner_hint)[:64] if (ref or owner_hint) else None,
        "name": str(name)[:120] if name else None,
    }])
    return set_id if ok else None


def next_pair(set_id: str, seen: set[str] | None = None, explore: float = 0.75) -> dict | None:
    """Mixed (epsilon-greedy) adaptive sampler for the pairwise ballot — concurrency-safe.

    Reads the *live* votes each call (so parallel voters see fresh standings), then with
    probability `explore` returns a RANDOM unseen pair (coverage + decorrelates parallel voters
    so they don't herd onto the same pair), else an ADAPTIVE pair (the closest-rated contest, for
    a top-1 boost). `seen` = pair keys 'a|b' (sorted) this voter already saw. Returns
    {"a": {...look}, "b": {...look}} or None when this voter has seen every pair.
    """
    import itertools
    import random as _random
    from app import rating

    seen = seen or set()
    rs = get_rank_set(set_id)
    if not rs:
        return None
    looks = rs.get("looks", [])
    by_id = {l.get("look_id"): l for l in looks}
    ids = list(by_id)
    if len(ids) < 2:
        return None

    def key(a, b):
        return "|".join(sorted((a, b)))

    candidates = [(a, b) for a, b in itertools.combinations(ids, 2) if key(a, b) not in seen]
    if not candidates:
        return None

    if _random.random() < explore or len(candidates) == 1:
        a, b = _random.choice(candidates)
    else:
        votes = _get(f"rank_votes?set_id=eq.{urllib.parse.quote(str(set_id))}"
                     f"&select=winner_look_id,loser_look_id&limit=5000") or []
        pairs = [(v.get("winner_look_id"), v.get("loser_look_id")) for v in votes
                 if v.get("winner_look_id") and v.get("loser_look_id")]
        strengths = rating.bradley_terry(ids, pairs)
        # adaptive: the unseen pair whose contestants are closest in strength (most uncertain)
        a, b = min(candidates, key=lambda pr: abs(strengths.get(pr[0], 1) - strengths.get(pr[1], 1)))

    if _random.random() < 0.5:  # randomize left/right to kill position bias
        a, b = b, a
    return {"a": by_id[a], "b": by_id[b], "remaining": len(candidates) - 1}


def record_confidence(set_id: str | None, look_id: str | None, owner_hint: str | None,
                      phase: str, value: int) -> bool:
    """Record a fit-confidence tap (phase 'pre' or 'post'). Δ(post-pre) is the theory's payoff."""
    if phase not in ("pre", "post"):
        return False
    try:
        v = max(0, min(10, int(value)))
    except Exception:
        return False
    return _post("confidence_marks", [{
        "set_id": str(set_id)[:64] if set_id else None,
        "look_id": str(look_id)[:64] if look_id else None,
        "owner_hint": str(owner_hint)[:64] if owner_hint else None,
        "phase": phase, "value": v,
    }])


def _get_all(path_select: str, limit: int = 10000) -> list:
    """Bulk read for /admin analytics. Returns [] on any error."""
    return _get(f"{path_select}&limit={int(limit)}") or []


def admin_snapshot() -> dict:
    """Aggregate everything the /admin dashboard needs, in one place (anon reads).

    Glicko-2 leaderboard, K-factor, confidence lift, and the share funnel by segment + channel.
    """
    from app import rating

    votes_raw = _get_all("rank_votes?select=set_id,winner_look_id,loser_look_id")
    looks = _get_all("looks?select=look_id,name,image_url,owner_hint,segment,confidence_self")
    referrals = _get_all("referrals?select=referrer_hint,activated")
    events = _get_all("garment_events?select=event_type,segment,channel")
    conf = _get_all("confidence_marks?select=set_id,look_id,owner_hint,phase,value")
    sets = _get_all("rank_sets?select=set_id,look_ids")

    # --- Glicko-2 leaderboard ---
    look_by_id = {l["look_id"]: l for l in looks}
    pairs = [(v.get("winner_look_id"), v.get("loser_look_id")) for v in votes_raw
             if v.get("winner_look_id") and v.get("loser_look_id")]
    ratings = rating.rate(list(look_by_id.keys()), pairs) if look_by_id else {}
    leaderboard = []
    for lid, rr in ratings.items():
        if rr["games"] == 0:
            continue
        lk = look_by_id.get(lid, {})
        leaderboard.append({"look_id": lid, "name": lk.get("name"), "image_url": lk.get("image_url"),
                            "segment": lk.get("segment"), **rr})
    leaderboard.sort(key=lambda x: x["rating"], reverse=True)

    # --- self <-> crowd convergence: avg Kendall's tau across ballots ---
    votes_by_set = {}
    for v in votes_raw:
        sid_ = v.get("set_id")
        if sid_ and v.get("winner_look_id") and v.get("loser_look_id"):
            votes_by_set.setdefault(sid_, []).append((v["winner_look_id"], v["loser_look_id"]))
    taus = []
    for st in sets:
        sid_ = st.get("set_id")
        lids = st.get("look_ids") or []
        if isinstance(lids, str):
            try:
                lids = json.loads(lids)
            except Exception:
                lids = []
        vp = votes_by_set.get(sid_, [])
        if len(lids) < 2 or not vp:
            continue
        conf_here = [(l, look_by_id.get(l, {}).get("confidence_self")) for l in lids]
        have = [c for c in conf_here if c[1] is not None]
        if len(have) < 2 or len({c[1] for c in have}) <= 1:
            continue
        self_order = [l for l, _ in sorted(have, key=lambda c: c[1], reverse=True)]
        crowd = sorted(lids, key=lambda l: rating.bradley_terry(lids, vp).get(l, 1), reverse=True)
        taus.append(rating.kendall_tau(self_order, crowd))
    avg_tau = (sum(taus) / len(taus)) if taus else None

    # --- K-factor (activations per distinct inviter) ---
    inviters = {r.get("referrer_hint") for r in referrals if r.get("referrer_hint")}
    activations = sum(1 for r in referrals if r.get("activated"))
    k_factor = (activations / len(inviters)) if inviters else 0.0

    # --- confidence lift (post - pre), per owner then averaged ---
    pre_by_owner, post_by_owner = {}, {}
    for c in conf:
        o = c.get("owner_hint"); ph = c.get("phase"); val = c.get("value")
        if o is None or val is None:
            continue
        (pre_by_owner if ph == "pre" else post_by_owner).setdefault(o, []).append(val)
    # seed 'pre' from looks.confidence_self when no explicit pre mark exists
    for l in looks:
        o = l.get("owner_hint"); cs = l.get("confidence_self")
        if o and cs is not None and o not in pre_by_owner:
            pre_by_owner.setdefault(o, []).append(cs)
    lifts = []
    for o, posts in post_by_owner.items():
        if o in pre_by_owner and pre_by_owner[o]:
            lifts.append(sum(posts) / len(posts) - sum(pre_by_owner[o]) / len(pre_by_owner[o]))
    avg_lift = (sum(lifts) / len(lifts)) if lifts else None

    # --- share funnel ---
    def _count(pred):
        return sum(1 for e in events if pred(e))
    by_segment, by_channel = {}, {}
    for e in events:
        if e.get("event_type") == "share":
            s = e.get("segment") or "—"; c = e.get("channel") or "—"
            by_segment[s] = by_segment.get(s, 0) + 1
            by_channel[c] = by_channel.get(c, 0) + 1

    return {
        "leaderboard": leaderboard[:50],
        "totals": {
            "looks": len(looks),
            "votes": len(pairs),
            "views": _count(lambda e: e.get("event_type") == "view"),
            "tries": _count(lambda e: e.get("event_type") == "try"),
            "shares": _count(lambda e: e.get("event_type") == "share"),
        },
        "network": {"inviters": len(inviters), "activations": activations,
                    "k_factor": round(k_factor, 3)},
        "confidence": {"avg_lift": (round(avg_lift, 2) if avg_lift is not None else None),
                       "samples": len(lifts)},
        "convergence": {"avg_tau": (round(avg_tau, 2) if avg_tau is not None else None),
                        "samples": len(taus)},
        "shares_by_segment": by_segment,
        "shares_by_channel": by_channel,
    }


def get_results(set_id: str) -> dict | None:
    """Rank a ballot's looks with Glicko-2 (owner's results view).

    Glicko-2 weighs *who* you beat, so with several voters it converges to a true order and only
    ties when the evidence really is a tie (e.g. a 3-way Condorcet cycle from a single voter).
    Returns {set_id, name, votes, decisive, looks:[{...,rating,rd,wins,games,win_rate,score}]}.
    Needs a select policy on rank_votes (docs/catalog_schema.sql).
    """
    from app import rating

    rs = get_rank_set(set_id)
    if not rs:
        return None
    votes = _get(f"rank_votes?set_id=eq.{urllib.parse.quote(str(set_id))}"
                 f"&select=winner_look_id,loser_look_id&limit=5000") or []
    pairs = [(v.get("winner_look_id"), v.get("loser_look_id")) for v in votes
             if v.get("winner_look_id") and v.get("loser_look_id")]
    src = rs.get("looks", [])
    ids = [lk.get("look_id") for lk in src]

    # head-to-head tallies for display
    wins, games = {i: 0 for i in ids}, {i: 0 for i in ids}
    for w, l in pairs:
        if w in wins:
            wins[w] += 1; games[w] += 1
        if l in games:
            games[l] += 1

    # Bradley-Terry / Plackett-Luce: strengths -> P(best) + per-rank probabilities
    strengths = rating.bradley_terry(ids, pairs) if ids else {}
    pbest = rating.p_best(strengths) if strengths else {}
    rankp = rating.rank_probabilities(strengths) if strengths else {}

    looks = []
    for lk in src:
        lid = lk.get("look_id")
        looks.append({**lk,
                      "p_best": round(pbest.get(lid, 1.0 / max(1, len(ids))) * 100),
                      "rank_probs": [round(x * 100) for x in rankp.get(lid, [])],
                      "wins": wins.get(lid, 0), "games": games.get(lid, 0),
                      "strength": round(strengths.get(lid, 1.0), 3)})
    looks.sort(key=lambda x: x["p_best"], reverse=True)
    for l in looks:  # bar score = P(best), floored so a nonzero bar always shows
        l["score"] = max(4, l["p_best"]) if pairs else 0

    crowd_order = [l["look_id"] for l in looks]

    # self <-> crowd convergence (Kendall's tau). Self-order = owner's per-look confidence
    # (higher confidence_self = they rate it better). Undefined if all equal / missing.
    conf = [(lk.get("look_id"), lk.get("confidence_self")) for lk in src]
    have_self = [c for c in conf if c[1] is not None]
    self_order, tau = None, None
    if len(have_self) >= 2 and len({c[1] for c in have_self}) > 1:
        self_order = [lid for lid, _ in sorted(have_self, key=lambda c: c[1], reverse=True)]
        if pairs:
            tau = round(rating.kendall_tau(self_order, crowd_order), 2)

    # decisive = clear leader: enough votes and a P(best) gap beyond noise
    decisive = len(looks) >= 2 and len(pairs) >= 3 and (looks[0]["p_best"] - looks[1]["p_best"]) >= 12

    return {"set_id": set_id, "name": rs.get("name"), "looks": looks,
            "votes": len(pairs), "decisive": decisive,
            "self_order": self_order, "crowd_order": crowd_order, "tau": tau}
