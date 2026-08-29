"""
Analytics event layer (analytics instrumentation spec).

"The gates ARE the events" — analytics is a Phase-1 dependency, not a backfill. Every
backend action emits a structured event carrying the common SPINE, so any metric can be
sliced by surface / entry_point / region / signed-in state, and the funnel
(intent -> render -> outcome) is legible end to end.

Design:
- The SPINE is required on every event (user_id OR guest_id, session_id, surface, ...).
- Guest events carry guest_id and STITCH onto user_id at signup (identity_stitch) so the
  pre-account funnel isn't a black hole.
- Social/creator events have their SCHEMA defined now but FIRE only in M2 (allow_m2).
- Emission goes to a pluggable sink; default prints JSON lines, and a real warehouse /
  the Events service is a drop-in sink later.
- Events carry ids + derived signals (confidence, verdict, gpu_seconds) — never raw
  biometrics (derive-and-discard). Pure stdlib, deterministic, unit-testable.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Callable
import json

SCHEMA_VERSION = "events-0.1.0"

# Render origins (analytics spec §2). entry_point is the field people forget and the one
# that answers "what actually drives renders" — required on render events.
ENTRY_POINTS = {"tap", "styleme", "surprise", "occasion", "weather", "colour",
                "rail", "inspo", "wardrobe", "scan"}

# Social/creator events: schema defined now, fired in M2 only (spec §9).
M2_EVENTS = {
    "tried_on": ("inspo_post_id", "creator"),
    "creator_render_share": ("creator", "look_id"),
    "provenance_tapped": ("creator",),
}

# Required props per M1 backend event (light validation + living schema doc).
EVENT_SCHEMA = {
    "avatar_build":    ("status",),                # start | done | abandon (+ duration_s)
    "twin_extracted":  ("slice", "model"),         # skin | measurements
    "eligibility":     ("allowed", "reason"),      # from can_render
    "input_cascade":   ("passed", "stage"),        # from the §6 cascade
    "render":          ("phase", "entry_point"),   # requested|started|completed|failed
    "token":           ("direction", "amount"),    # earned | spent
    "confirm_gate":    ("action",),                # viewed | abandoned
    "identity_stitch": ("from_guest_id", "to_user_id"),
    "feedback":        ("severity", "route"),       # live report -> ticket (feedback loop)
}


@dataclass
class Spine:
    session_id: str
    surface: str
    app_version: str
    device_os: str
    signed_in: bool
    user_id: Optional[str] = None
    guest_id: Optional[str] = None
    entry_point: Optional[str] = None
    region: Optional[str] = None

    def validate(self) -> None:
        if not self.user_id and not self.guest_id:
            raise ValueError("spine needs a user_id or a guest_id")
        if self.entry_point is not None and self.entry_point not in ENTRY_POINTS:
            raise ValueError(f"unknown entry_point {self.entry_point!r}")


Sink = Callable[[dict], None]


def stdout_sink(event: dict) -> None:
    print(json.dumps(event, separators=(",", ":")))


class MemorySink:
    """Collects events in memory — for tests, local inspection, and dashboards."""
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)


class Analytics:
    def __init__(self, sink: Sink = stdout_sink, allow_m2: bool = False) -> None:
        self.sink = sink
        self.allow_m2 = allow_m2

    def track(self, event: str, spine: Spine, ts: Optional[str] = None, **props) -> Optional[dict]:
        spine.validate()
        if event in M2_EVENTS and not self.allow_m2:
            return None   # schema exists; fires in M2 only
        required = EVENT_SCHEMA.get(event, M2_EVENTS.get(event, ()))
        missing = [k for k in required if props.get(k) is None]
        if missing:
            raise ValueError(f"event {event!r} missing required props {missing}")
        rec = {
            "schema_version": SCHEMA_VERSION,
            "event": event,
            "ts": ts or datetime.now(timezone.utc).isoformat(),
            **asdict(spine),
            "props": props,
        }
        self.sink(rec)
        return rec

    # --- typed helpers for the backend's key events (so callers can't forget props) ---
    def avatar_build(self, spine: Spine, status: str, duration_s: Optional[float] = None, **x):
        """status: start | done | abandon — 'the gate for everything' (spec §1)."""
        return self.track("avatar_build", spine, status=status, duration_s=duration_s, **x)

    def twin_extracted(self, spine: Spine, slice: str, model: str,
                       confidence: Optional[float] = None, needs_confirm: Optional[bool] = None, **x):
        return self.track("twin_extracted", spine, slice=slice, model=model,
                          confidence=confidence, needs_confirm=needs_confirm, **x)

    def eligibility(self, spine: Spine, allowed: bool, reason: str, **x):
        return self.track("eligibility", spine, allowed=allowed, reason=reason, **x)

    def input_cascade(self, spine: Spine, passed: bool, stage: int,
                      quality_flags: Optional[list] = None, **x):
        return self.track("input_cascade", spine, passed=passed, stage=stage,
                          quality_flags=quality_flags or [], **x)

    def render(self, spine: Spine, phase: str, entry_point: str,
               gpu_seconds: Optional[float] = None, latency_ms: Optional[int] = None,
               fidelity_score: Optional[float] = None, fail_reason: Optional[str] = None,
               source: Optional[str] = None, **x):
        """phase: requested|started|completed|failed. 'completed' MUST carry gpu_seconds."""
        if entry_point not in ENTRY_POINTS:
            raise ValueError(f"unknown render entry_point {entry_point!r}")
        if phase == "completed" and gpu_seconds is None:
            raise ValueError("render completed must carry gpu_seconds (unit economics)")
        return self.track("render", spine, phase=phase, entry_point=entry_point,
                          gpu_seconds=gpu_seconds, latency_ms=latency_ms,
                          fidelity_score=fidelity_score, fail_reason=fail_reason,
                          source=source, **x)

    def token(self, spine: Spine, direction: str, amount: int,
              source: Optional[str] = None, on: Optional[str] = None, **x):
        """direction: earned | spent."""
        return self.track("token", spine, direction=direction, amount=amount,
                          source=source, on=on, **x)

    def confirm_gate(self, spine: Spine, action: str, spent: Optional[bool] = None,
                     cost: Optional[int] = None, balance_at_gate: Optional[int] = None, **x):
        """action: viewed | abandoned — the price-at-peak bounce watch (spec §2)."""
        return self.track("confirm_gate", spine, action=action, spent=spent,
                          cost=cost, balance_at_gate=balance_at_gate, **x)

    def feedback(self, spine: Spine, severity: str, route: str, kind: Optional[str] = None,
                 device_specific: Optional[bool] = None, dedup_key: Optional[str] = None, **x):
        """A live report entered the feedback loop. route: standard | device_farm.
        Not biometric — carries device/screen/severity, never a photo or measurement."""
        return self.track("feedback", spine, severity=severity, route=route, kind=kind,
                          device_specific=device_specific, dedup_key=dedup_key, **x)

    def stitch_identity(self, spine: Spine, from_guest_id: str, to_user_id: str, **x):
        """At signup: link the guest's pre-account events onto the new user_id."""
        return self.track("identity_stitch", spine, from_guest_id=from_guest_id,
                          to_user_id=to_user_id, **x)
