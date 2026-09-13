"""Optional training scaffolds (hair texture). Torch is an optional dep — see
train/requirements-train.txt. Nothing here is imported by the GPU-free Service A runtime;
inference wires in via train/infer.py only when a trained model is present."""
