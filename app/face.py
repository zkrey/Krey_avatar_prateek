"""
Face-extraction orchestrator — composes the face attribute slices into the body_models
face portion + the §6 recognition score, from whatever clean samples are available.

`assemble_face` is pure/deterministic given samples, so it is fully unit-testable without
a photo. The image samplers that PRODUCE the samples live in the pipeline: skin uses
`skin_tone.extract_skin_samples` (built); hair (MediaPipe hair_segmenter -> mask) and iris
(face_landmarker -> eye crops) samplers are model-backed and are a documented hook here
(`sample_hair_and_eyes`) until those models are wired — same pattern as the pose model.
"""
from __future__ import annotations
from typing import Optional, Sequence, Tuple
from app import monk, hair, eye
from app.body_models import assemble_body_models
from app.recognition import recognition_from_body_models

RGB = Tuple[int, int, int]


def assemble_face(
    skin_samples: Optional[Sequence[RGB]] = None,
    hair_samples: Optional[Sequence[RGB]] = None,
    iris_samples: Optional[Sequence[RGB]] = None,
    hair_features: Optional[dict] = None,
) -> dict:
    """Compose skin/hair/eye slices (each computed only if its samples exist) + recognition."""
    skin_tone = monk.classify(skin_samples) if skin_samples else None
    hair_colour = hair.classify_hair_colour(hair_samples) if hair_samples else None
    hair_texture = hair.classify_hair_texture(hair_features)          # stub if features is None
    eye_colour = eye.classify_eye_colour(iris_samples) if iris_samples else None

    record = assemble_body_models(skin_tone=skin_tone, hair_colour=hair_colour,
                                  hair_texture=hair_texture, eye_colour=eye_colour)
    record["avatar_confidence"] = recognition_from_body_models(record)
    return record


def face_slices_present(record: dict) -> list:
    """Which face attributes actually got a value (for the no-usable-face decision)."""
    return [k for k in ("skin_tone", "hair_colour", "eye_colour")
            if record.get(k) and record[k].get("value") is not None]


def sample_hair_and_eyes(img_bgr):
    """
    Returns (hair_samples, iris_samples, hair_region_bgr) via the model-backed pipeline
    (MediaPipe hair_segmenter + face_landmarker). Imported lazily so this module stays
    pure/GPU-free to import; when a model is absent the pipeline returns empties and the
    face endpoint composes whatever IS available (skin), degrading cleanly.
    """
    from app.face_pipeline import sample_hair_and_eyes as _impl
    return _impl(img_bgr)
