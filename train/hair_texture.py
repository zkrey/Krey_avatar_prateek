"""
Hair-texture classifier — training scaffold (SINGLE-label: straight / wavy / curly / coily).

Fills the one unbuilt slice of the twin (docs/hair_texture_plan.md). Design choices baked in:
  - single-label 4-class softmax + CrossEntropy (texture is one dominant class), NOT the
    multi-label BCE pattern — colour is already deterministic (app/hair.py), length isn't in
    the identity contract.
  - source folder names are remapped to our taxonomy (kinky -> coily; dreadlocks/braids/etc.
    dropped as styles, not textures).
  - CPU-friendly backbone (ResNet18) so inference stays in the GPU-free service.

Torch is an OPTIONAL dependency (train/requirements-train.txt); it is lazy-imported so the
repo imports and tests without it. Run on a machine with the data (+ ideally a GPU):

    pip install -r train/requirements-train.txt
    python -m train.hair_texture --data data/hair_type_kavyasree --out models/hair_texture

Then point inference at it:  KREY_HAIR_TEXTURE_MODEL=models/hair_texture/model.pt  (train/infer.py).
"""
from __future__ import annotations
import os
import json
import argparse
from collections import Counter
from typing import Optional

# Our texture taxonomy (the hair_texture slot's allowed values).
CLASSES = ["straight", "wavy", "curly", "coily"]
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}

# Map source dataset folder names -> our taxonomy. None = drop (a style, not a texture).
REMAP = {
    "straight": "straight",
    "wavy": "wavy",
    "curly": "curly",
    "coily": "coily",
    "kinky": "coily",          # kavyasreeb's "kinky" is our coily
    "afro": "coily",
    "dreadlocks": None,        # styles, not textures — dropped
    "dreads": None,
    "braids": None,
    "bald": None,
}

_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def remap_label(name: str) -> Optional[str]:
    """Source folder name -> our class, or None to drop. Unknown names also drop."""
    return REMAP.get((name or "").strip().lower())


def build_samples(root: str):
    """Walk an ImageFolder-style root; return (samples, kept, dropped).
    samples = [(path, class_idx)] after remap. Pure stdlib — testable without torch."""
    samples = []
    kept, dropped = Counter(), Counter()
    entries = sorted(os.listdir(root)) if os.path.isdir(root) else []
    for entry in entries:
        sub = os.path.join(root, entry)
        if not os.path.isdir(sub):
            continue
        mapped = remap_label(entry)
        for r, _, files in os.walk(sub):
            for f in files:
                if not f.lower().endswith(_EXTS):
                    continue
                if mapped is None or mapped not in CLASS_INDEX:
                    dropped[entry] += 1
                else:
                    samples.append((os.path.join(r, f), CLASS_INDEX[mapped]))
                    kept[mapped] += 1
    return samples, dict(kept), dict(dropped)


# --------------------------------------------------------------------------- #
# Everything below needs torch/torchvision (lazy-imported).                    #
# --------------------------------------------------------------------------- #
def _transforms(train: bool):
    from torchvision import transforms
    if train:
        return transforms.Compose([
            transforms.Resize((256, 256)),
            transforms.RandomResizedCrop(224, scale=(0.7, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(0.2, 0.2, 0.2, 0.02),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])


def _dataset(samples, train: bool):
    from torch.utils.data import Dataset
    from PIL import Image
    tf = _transforms(train)

    class HairDS(Dataset):
        def __len__(self):
            return len(samples)

        def __getitem__(self, i):
            path, y = samples[i]
            return tf(Image.open(path).convert("RGB")), y

    return HairDS()


def train(data_dir: str, out_dir: str = "models/hair_texture", epochs: int = 12,
          batch_size: int = 32, lr: float = 1e-4, val_split: float = 0.2, seed: int = 42):
    """Transfer-learn a ResNet18 texture head. Saves best-val checkpoint + metrics json."""
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, random_split
    from torchvision import models

    samples, kept, dropped = build_samples(data_dir)
    if len(samples) < len(CLASSES) * 2:
        raise SystemExit(f"Too few usable images ({len(samples)}). kept={kept} dropped={dropped}")
    print(f"kept per class: {kept}   dropped (styles/unknown): {dropped}")

    torch.manual_seed(seed)
    full = _dataset(samples, train=True)
    n_val = max(1, int(len(full) * val_split))
    n_train = len(full) - n_val
    train_ds, val_ds = random_split(full, [n_train, n_val],
                                    generator=torch.Generator().manual_seed(seed))
    train_ld = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=2)
    val_ld = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=2)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    net = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
    net.fc = nn.Linear(net.fc.in_features, len(CLASSES))
    net = net.to(device)
    crit = nn.CrossEntropyLoss()
    opt = torch.optim.Adam(net.parameters(), lr=lr)

    os.makedirs(out_dir, exist_ok=True)
    best_acc, best_metrics = -1.0, {}
    for ep in range(1, epochs + 1):
        net.train()
        for xb, yb in train_ld:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            crit(net(xb), yb).backward()
            opt.step()

        # validation + per-class accuracy (the fairness signal lives here)
        net.eval()
        correct = Counter()
        total = Counter()
        with torch.no_grad():
            for xb, yb in val_ld:
                xb = xb.to(device)
                pred = net(xb).argmax(1).cpu()
                for p, y in zip(pred.tolist(), yb.tolist()):
                    total[y] += 1
                    correct[y] += int(p == y)
        overall = sum(correct.values()) / max(1, sum(total.values()))
        per_class = {CLASSES[c]: round(correct[c] / total[c], 3) for c in total}
        print(f"epoch {ep:2d}  val_acc={overall:.3f}  per_class={per_class}")
        if overall > best_acc:
            best_acc = overall
            best_metrics = {"val_acc": round(overall, 3), "per_class_acc": per_class,
                            "epoch": ep, "kept": kept, "dropped": dropped,
                            "n_train": n_train, "n_val": n_val}
            torch.save({"state_dict": net.state_dict(), "classes": CLASSES,
                        "backbone": "resnet18", "meta": best_metrics},
                       os.path.join(out_dir, "model.pt"))

    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump(best_metrics, f, indent=2)
    print(f"best val_acc={best_acc:.3f} -> {out_dir}/model.pt")
    print("FAIRNESS GATE: confirm per-class acc on INDIAN curly/coily before trusting "
          "(docs/hair_texture_plan.md) — web-sourced training data is not Indian.")
    return best_metrics


def main(argv=None):
    ap = argparse.ArgumentParser(description="Train the hair-texture classifier.")
    ap.add_argument("--data", required=True, help="ImageFolder root (source folders remapped)")
    ap.add_argument("--out", default="models/hair_texture")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--val-split", type=float, default=0.2)
    a = ap.parse_args(argv)
    train(a.data, out_dir=a.out, epochs=a.epochs, batch_size=a.batch_size,
          lr=a.lr, val_split=a.val_split)


if __name__ == "__main__":
    main()
