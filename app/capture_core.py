"""
Capture-session aggregation — the deterministic brain of the 5-photo pipeline (spec:
5-photo aggregation lifts per-attribute accuracy ~65% -> ~84%). GPU-free, pure stdlib,
so it is fully unit-testable without a face model or a photo — the ArcFace embeddings,
timestamps and attribute readings are produced by the pipeline (`capture_session.py`)
and passed in as plain numbers.

Two aggregations run on the same set (see docs/scope_bakeins.md):
  - IDENTITY (stable): cluster faces by embedding similarity, pick the user's cluster,
    score how consistently the same face recurs -> identity confidence + a soft-confirm
    decision (accept / reconfirm / retake) instead of a hard reject.
  - APPEARANCE: pool each attribute across the user's good frames. Identity-stable
    attributes (eye colour) are confidence-weighted; time-varying ones (build, hair)
    are RECENCY-weighted by capture date so the twin reflects how the user looks NOW.
"""
from __future__ import annotations
from typing import Optional, Sequence, Mapping
from collections import defaultdict
from datetime import date, datetime
import math
import re

_FNAME_DATE = re.compile(r"(20\d{2})[-_]?(\d{2})(\d{2})")

# soft-confirm thresholds (provisional — calibrate on real capture data)
ACCEPT_FLOOR = 0.60
RECONFIRM_FLOOR = 0.35
SAME_FACE_COSINE = 0.35        # ArcFace: >= this = same identity
UNDATED_WEIGHT = 0.25          # a photo with no readable date still corroborates, softly
DEFAULT_HALF_LIFE_DAYS = 540   # appearance recency half-life (~18 months)


# --------------------------------------------------------------------------- #
# Timestamps (the ageing signal)                                              #
# --------------------------------------------------------------------------- #
def parse_capture_date(exif_datetime: Optional[str], filename: Optional[str] = None) -> Optional[str]:
    """
    Best-effort capture date (ISO 'YYYY-MM-DD') from EXIF, falling back to a date encoded
    in the filename (WhatsApp strips EXIF; some cameras corrupt it with null bytes). Never
    guesses 'today' — returns None when nothing is readable, and the caller treats undated
    photos as identity corroboration only, never as the recency anchor.
    """
    if exif_datetime:
        s = exif_datetime.replace("\x00", "").strip()
        m = re.match(r"(20\d{2})[:\-/](\d{2})[:\-/](\d{2})", s)
        if m:
            iso = _safe_date(m.group(1), m.group(2), m.group(3))
            if iso:
                return iso
    if filename:
        m = _FNAME_DATE.search(filename)
        if m:
            iso = _safe_date(m.group(1), m.group(2), m.group(3))
            if iso:
                return iso
    return None


def _safe_date(y: str, mo: str, d: str) -> Optional[str]:
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Identity clustering + user selection                                        #
# --------------------------------------------------------------------------- #
def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-9)


def cluster_by_similarity(embeddings: Sequence[Sequence[float]],
                          threshold: float = SAME_FACE_COSINE) -> list:
    """Greedy single-link clustering by cosine similarity. Deterministic. Returns a label per face."""
    n = len(embeddings)
    labels = [-1] * n
    cid = 0
    for i in range(n):
        if labels[i] != -1:
            continue
        labels[i] = cid
        for j in range(i + 1, n):
            if labels[j] == -1 and _cosine(embeddings[i], embeddings[j]) >= threshold:
                labels[j] = cid
        cid += 1
    return labels


def members_by_cluster(labels: Sequence[int]) -> dict:
    out = defaultdict(list)
    for i, c in enumerate(labels):
        out[c].append(i)
    return dict(out)


def select_user_cluster(labels: Sequence[int], dates: Sequence[Optional[str]]) -> Optional[int]:
    """
    The user is the identity that recurs the most — spanning the most distinct capture
    dates, tie-broken by face count. (In a real 5-photo capture that's the deliberate
    subject; bystanders appear in fewer frames.) None when there are no faces.
    """
    members = members_by_cluster(labels)
    if not members:
        return None

    def score(c):
        idxs = members[c]
        n_dates = len({dates[i] for i in idxs if dates[i]})
        return (n_dates, len(idxs))

    return max(members, key=score)


def intra_similarities(embeddings: Sequence[Sequence[float]], idxs: Sequence[int]) -> list:
    return [_cosine(embeddings[a], embeddings[b])
            for k, a in enumerate(idxs) for b in idxs[k + 1:]]


def identity_confidence(intra_sims: Sequence[float], n_frames: int,
                        n_dates: int, target_frames: int = 5) -> dict:
    """
    How sure are we this is one consistent person, and is there enough evidence?
    consistency = how tightly the matched faces agree; evidence = frame coverage vs the
    5-photo target. Never surfaced to the user as a number.
    """
    mean_sim = sum(intra_sims) / len(intra_sims) if intra_sims else 1.0 if n_frames == 1 else 0.0
    consistency = max(0.0, min(1.0, (mean_sim - 0.30) / 0.50))   # 0.30..0.80 cos -> 0..1
    evidence = min(1.0, n_frames / target_frames)
    overall = round(0.70 * consistency + 0.30 * evidence, 3)
    return {
        "overall": overall,
        "consistency": round(consistency, 3),
        "evidence": round(evidence, 3),
        "mean_cosine": round(mean_sim, 3),
        "n_frames": n_frames,
        "n_dates": n_dates,
        "surfaced_to_user": False,
    }


def capture_decision(identity_overall: float, n_user_frames: int) -> str:
    """Soft-confirm ladder: retake only as a last resort (matches the UX doctrine)."""
    if n_user_frames <= 0:
        return "retake_no_face"
    if identity_overall >= ACCEPT_FLOOR:
        return "accept"
    if identity_overall >= RECONFIRM_FLOOR:
        return "reconfirm"          # one-tap 'is this you?', not a re-upload
    return "retake_low_confidence"


# --------------------------------------------------------------------------- #
# Appearance aggregation (recency-aware)                                       #
# --------------------------------------------------------------------------- #
def recency_weights(dates: Sequence[Optional[str]],
                    half_life_days: int = DEFAULT_HALF_LIFE_DAYS) -> list:
    """
    Weight each frame by how recent it is: freshest date = 1.0, decaying by half-life;
    undated frames get a small fixed baseline (they corroborate, don't anchor 'now').
    All-undated -> equal weights (nothing to order by).
    """
    parsed = [_to_date(d) for d in dates]
    valid = [p for p in parsed if p]
    if not valid:
        return [1.0] * len(dates)
    newest = max(valid)
    out = []
    for p in parsed:
        if p is None:
            out.append(UNDATED_WEIGHT)
        else:
            age_days = (newest - p).days
            out.append(round(0.5 ** (age_days / half_life_days), 4))
    return out


def _to_date(iso: Optional[str]) -> Optional[date]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).date()
    except (ValueError, TypeError):
        return None


def aggregate_categorical(observations: Sequence[Mapping], mode: str = "stable",
                          dates: Optional[Sequence[Optional[str]]] = None,
                          half_life_days: int = DEFAULT_HALF_LIFE_DAYS) -> Optional[dict]:
    """
    Fuse one categorical attribute (skin band / hair colour / eye colour / texture) across
    frames. Each observation = {'value', 'confidence'}.
      mode 'stable' -> weight = confidence            (identity-stable: eye colour)
      mode 'recent' -> weight = confidence * recency   (time-varying: hair, build)
    Returns the winning value, a fused confidence, agreement, and the vote distribution.
    """
    obs = [o for o in observations if o and o.get("value") is not None]
    if not obs:
        return None
    if mode == "recent":
        if dates is None:
            raise ValueError("mode 'recent' needs per-frame dates")
        rw = recency_weights(dates, half_life_days)
        rw = [rw[i] for i, o in enumerate(observations) if o and o.get("value") is not None]
    else:
        rw = [1.0] * len(obs)

    tally: dict = defaultdict(float)
    total = 0.0
    for o, w in zip(obs, rw):
        weight = float(o.get("confidence", 0.5)) * w
        tally[o["value"]] += weight
        total += weight
    if total <= 0:
        return None
    winner = max(tally, key=tally.get)
    agreement = round(tally[winner] / total, 3)
    return {
        "value": winner,
        "confidence": round(min(0.99, agreement * (0.6 + 0.4 * min(1.0, len(obs) / 5))), 3),
        "agreement": agreement,
        "n_frames": len(obs),
        "mode": mode,
        "distribution": {k: round(v / total, 3) for k, v in sorted(tally.items(), key=lambda x: -x[1])},
        "needs_confirm": agreement < 0.60,
    }
