"""
Face-extraction orchestrator — composes the face attribute slices into the body_models
face portion + the §6 recognition score, from whatever clean samples are available.

`assemble_face` is pure/deterministic given samples, so it is fully unit-testable without
a photo. The image samplers that PRODUCE the samples live in the pipeline
(`face_pipeline`): one MediaPipe face_landmarker pass drives the single-face gate + skin
patches + iris crops, and the hair_segmenter yields the hair mask. `sample_face` wraps
that pipeline (lazily, so this module stays pure to import).
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


def sample_face(img_bgr) -> dict:
    """
    Run the model-backed pipeline (MediaPipe face_landmarker + hair_segmenter) and return
    the single-face gate + clean skin/hair/iris samples:
        {gate, n_faces, skin_samples, hair_samples, iris_samples, hair_region}
    Imported lazily so this module stays pure/GPU-free to import. `gate` is the decision:
    'ok' (one clear face) yields samples; 'no_face' / 'multiple_faces' come back empty so
    the endpoint asks for a retake instead of trusting a group photo.
    """
    from app.face_pipeline import sample_face as _impl
    return _impl(img_bgr)
