"""
The `body_models` record — Service A's output contract (spec §4).

A compact, derive-and-discard record describing a user's twin. Each extraction
slice fills its own part of it, and the parts compose without touching each other:

    body_models = {
        schema_version,
        skin_tone:     <slice 1: monk.classify(...)>        | None,
        measurements:  <slice 2: per-part width/depth/circ/confidence> | None,
        body_shape:    <computed shape + declared cross-check>          | None,
        accuracy_ledger: <backend-only confidence, spec §6>             | None,
    }

This module only ASSEMBLES the record from slices already computed elsewhere, so
it stays pure stdlib and unit-testable. Keeping the assembler separate is what lets
slice 1 (skin) and slice 2 (measurements) stay independent while sharing one shape.

Invariants carried here (from the spec):
- derive-and-discard: this record is the compact artefact; raw photos are not part
  of it and get short retention upstream.
- the accuracy ledger is backend-only and never surfaced to the user.
"""
from __future__ import annotations
from typing import Optional, Mapping
from app.measure_core import SCHEMA_VERSION


def empty_body_models() -> dict:
    """A body_models record with every slice unset."""
    return {
        "schema_version": SCHEMA_VERSION,
        "skin_tone": None,
        "hair_colour": None,
        "hair_texture": None,
        "eye_colour": None,
        "measurements": None,
        "body_shape": None,
        "accuracy_ledger": None,
        "avatar_confidence": None,   # §6 recognition score (backend-only) — see app/recognition.py
    }


def assemble_body_models(
    skin_tone: Optional[Mapping] = None,
    measurements: Optional[Mapping] = None,
    body_shape: Optional[Mapping] = None,
    accuracy_ledger: Optional[Mapping] = None,
    avatar_confidence: Optional[Mapping] = None,
    hair_colour: Optional[Mapping] = None,
    hair_texture: Optional[Mapping] = None,
    eye_colour: Optional[Mapping] = None,
) -> dict:
    """Compose whatever slices are available into one body_models record."""
    record = empty_body_models()
    for key, val in (("skin_tone", skin_tone), ("hair_colour", hair_colour),
                     ("hair_texture", hair_texture), ("eye_colour", eye_colour),
                     ("measurements", measurements), ("body_shape", body_shape),
                     ("accuracy_ledger", accuracy_ledger),
                     ("avatar_confidence", avatar_confidence)):
        if val is not None:
            record[key] = dict(val)
    return record
