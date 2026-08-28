"""
Twin persistence — keep the COMPACT record, never raw biometrics (derive-and-discard).

The raw photos are already deleted at the endpoint the moment the record is derived; this
layer is what we DO keep: the small body_models record (skin/hair/eye/measurements/shape/
style + confidences). Two invariants live here:

  - WHITELIST: only the known body_models slots are persisted (`_SLOTS`) — a defensive
    filter so no raw pixels, face embeddings, or stray large arrays can ever reach storage.
  - ACCOUNT-KEYED: persistence requires an account user_id (guests never persist biometric-
    derived data — the eligibility wall already blocks guest biometric processing upstream).
  - ERASURE: delete() removes the record entirely (DPDP right-to-erasure).

save() MERGES slices over any existing record, so the face capture and the body capture
accumulate into ONE twin per user across separate calls. The in-memory store is the tested
reference; a real deployment swaps in a DB/file backend behind the same tiny interface.
"""
from __future__ import annotations
from typing import Optional, Mapping
from datetime import datetime, timezone
from app.measure_core import SCHEMA_VERSION

# The only fields we persist. Anything else in a passed record is dropped on the floor.
_SLOTS = ("skin_tone", "hair_colour", "hair_texture", "eye_colour", "measurements",
          "body_shape", "accuracy_ledger", "avatar_confidence", "style_profile")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact(record: Optional[Mapping]) -> dict:
    """Keep only the whitelisted, non-null body_models slots — the derive-and-discard guard."""
    return {k: record[k] for k in _SLOTS if (record or {}).get(k) is not None}


def merge_slices(base: Optional[Mapping], update: Optional[Mapping]) -> dict:
    """Overlay update's slices onto base; a present slice wins, missing ones are untouched."""
    out = {k: v for k, v in (base or {}).items() if k in _SLOTS}
    for k, v in compact(update).items():
        out[k] = v
    return out


class MemoryTwinStore:
    """Dict-backed reference store — save/merge, get, delete. Tested; swap for a DB backend."""

    def __init__(self) -> None:
        self._d: dict = {}

    def save(self, user_id: str, record: Mapping, source: str = "capture") -> dict:
        if not user_id:
            raise ValueError("persistence requires an account user_id")
        prev = self._d.get(user_id)
        env = {
            "user_id": user_id,
            "schema_version": SCHEMA_VERSION,
            "record": merge_slices(prev["record"] if prev else {}, record),
            "created_at": prev["created_at"] if prev else _now(),
            "updated_at": _now(),
            "version": (prev["version"] + 1) if prev else 1,
            "last_source": source,
            "raw_retained": False,          # invariant: raw photos are never stored here
        }
        self._d[user_id] = env
        return env

    def get(self, user_id: str) -> Optional[dict]:
        return self._d.get(user_id)

    def delete(self, user_id: str) -> bool:
        """Right-to-erasure — remove the record entirely. True if something was removed."""
        return self._d.pop(user_id, None) is not None

    def exists(self, user_id: str) -> bool:
        return user_id in self._d
