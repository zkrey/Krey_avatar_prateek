"""
Hair-texture inference — the drop-in for the `hair_texture` slot.

Returns the exact slot shape the twin expects, so wiring it in changes nothing downstream:
    {"value": "wavy", "available": True, "confidence": 0.83}

Degrades cleanly to {"available": False} when torch or a trained checkpoint is missing — the
same behaviour as today's stub in app/face.py, so the recognition score just renormalises.
Point it at a model with KREY_HAIR_TEXTURE_MODEL=/path/to/model.pt (or pass model_path).

Integration (later, one line in app/face.py's hair path):
    from train.infer import read_hair_texture
    hair_texture = read_hair_texture(hair_region_or_image)   # np.ndarray | PIL.Image | path
"""
from __future__ import annotations
import os
from typing import Optional

_UNAVAILABLE = {"value": None, "available": False, "confidence": None}
_CACHE: dict = {}


def _model_path(explicit: Optional[str]) -> Optional[str]:
    p = explicit or os.environ.get("KREY_HAIR_TEXTURE_MODEL")
    return p if p and os.path.exists(p) else None


def _load(path):
    if path in _CACHE:
        return _CACHE[path]
    import torch
    from torchvision import models
    import torch.nn as nn
    ckpt = torch.load(path, map_location="cpu")
    classes = ckpt.get("classes", ["straight", "wavy", "curly", "coily"])
    net = models.resnet18()
    net.fc = nn.Linear(net.fc.in_features, len(classes))
    net.load_state_dict(ckpt["state_dict"])
    net.eval()
    _CACHE[path] = (net, classes)
    return net, classes


def _to_pil(image):
    from PIL import Image
    if isinstance(image, str):
        return Image.open(image).convert("RGB")
    if hasattr(image, "convert"):            # already a PIL image
        return image.convert("RGB")
    # assume an HxWxC array (e.g. a cv2/np hair-region crop). cv2 is BGR -> flip to RGB.
    try:
        import numpy as np
        arr = np.asarray(image)
        if arr.ndim == 3 and arr.shape[2] == 3:
            arr = arr[:, :, ::-1]
        return Image.fromarray(arr.astype("uint8")).convert("RGB")
    except Exception:
        return None


def read_hair_texture(image, model_path: Optional[str] = None,
                      confirm_below: float = 0.60) -> dict:
    """image: path | PIL.Image | np.ndarray(HxWxC). Returns the hair_texture slot dict."""
    path = _model_path(model_path)
    if path is None:
        return dict(_UNAVAILABLE)
    try:
        import torch
        from torchvision import transforms
        net, classes = _load(path)
        pil = _to_pil(image)
        if pil is None:
            return dict(_UNAVAILABLE)
        tf = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
        with torch.no_grad():
            probs = torch.softmax(net(tf(pil).unsqueeze(0)), dim=1)[0]
        conf, idx = float(probs.max()), int(probs.argmax())
        return {"value": classes[idx], "available": True,
                "confidence": round(conf, 3), "needs_confirm": conf < confirm_below,
                "model": "hair-texture-resnet18-v1"}
    except Exception:
        return dict(_UNAVAILABLE)
