"""
Skin-tone validation / calibration harness.

Runs Krey's deterministic Monk reader (app/monk.py — CIEDE2000) over a folder of images
and writes a report: the tone distribution, the needs_confirm / off-swatch rates, and —
when the folder is labelled by Monk bucket (ImageFolder-style, subdir names "1".."10") —
agreement vs those labels. This produces the "early info" for validation + calibration
(docs/skin_data_plan.md); raw images stay out of git, the derived report is committed.

Skin pixels per image come from the PRODUCTION extractor (app/skin_tone, needs cv2) when
available — the real thing we want to validate — else a coarse PIL centre-region proxy,
which is flagged in the report. Pure-stdlib aggregation (statistics), Pillow for the proxy.

    python -m bench.skin_report --data data/dermacon_in/images --name dermacon_in
    python -m bench.skin_report --data data/scin/images --name scin --limit 500
"""
from __future__ import annotations
import argparse
import json
import os
import statistics
from collections import Counter

_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def _iter_images(data_dir):
    """Yield (path, label). Label = immediate subdir name if the folder is ImageFolder-style,
    else None. Numeric subdir names are treated as Monk-bucket ground truth downstream."""
    entries = sorted(os.listdir(data_dir)) if os.path.isdir(data_dir) else []
    subdirs = [d for d in entries if os.path.isdir(os.path.join(data_dir, d))]
    if subdirs:
        for d in subdirs:
            for root, _, files in os.walk(os.path.join(data_dir, d)):
                for f in sorted(files):
                    if f.lower().endswith(_EXTS):
                        yield os.path.join(root, f), d
    else:
        for root, _, files in os.walk(data_dir):
            for f in sorted(files):
                if f.lower().endswith(_EXTS):
                    yield os.path.join(root, f), None


def image_to_skin_rgbs(path, max_samples=200):
    """Return (samples, method). Prefer the production cv2 extractor; else a PIL proxy."""
    try:
        import cv2  # noqa
        import numpy as np  # noqa
        from app.skin_tone import extract_skin_samples
        img = cv2.imread(str(path))
        if img is not None:
            found = extract_skin_samples(img)
            if found.get("ok") and found.get("samples"):
                return list(found["samples"])[:max_samples], "cv2"
    except Exception:
        pass
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    box = im.crop((int(w * 0.30), int(h * 0.20), int(w * 0.70), int(h * 0.60)))
    px = list(box.getdata())
    skin = [(r, g, b) for (r, g, b) in px if r > g >= b and r > 60 and (r - b) > 10]
    use = skin or px
    step = max(1, len(use) // max_samples)
    return use[::step][:max_samples], "pil-proxy"


def _summarize(rows, name, methods):
    n = len(rows)
    buckets = Counter(r["value"] for r in rows)
    cont = [r["monk_continuous"] for r in rows if r["monk_continuous"] is not None]
    de = [r["delta_e"] for r in rows]
    from app.monk import OFF_SWATCH_DE
    summary = {
        "dataset": name,
        "n_images_read": n,
        "skin_extractor": methods,
        "monk_bucket_counts": {str(k): buckets[k] for k in sorted(buckets)},
        "monk_continuous_mean": round(statistics.fmean(cont), 2) if cont else None,
        "monk_continuous_median": round(statistics.median(cont), 2) if cont else None,
        "needs_confirm_rate": round(sum(r["needs_confirm"] for r in rows) / n, 3) if n else None,
        "off_swatch_rate": round(sum(1 for r in rows if r["delta_e"] > OFF_SWATCH_DE) / n, 3) if n else None,
        "delta_e_mean": round(statistics.fmean(de), 2) if de else None,
        "delta_e_p90": round(sorted(de)[int(0.9 * (len(de) - 1))], 2) if de else None,
    }
    # If labels are Monk integers, score agreement (the calibration signal).
    labelled = [(r["label"], r["value"]) for r in rows
                if r["label"] is not None and str(r["label"]).isdigit()]
    if labelled:
        exact = sum(1 for lab, val in labelled if int(lab) == val)
        within1 = sum(1 for lab, val in labelled if abs(int(lab) - val) <= 1)
        mae = statistics.fmean(abs(int(lab) - val) for lab, val in labelled)
        summary["labelled"] = {
            "n": len(labelled),
            "exact_bucket_agreement": round(exact / len(labelled), 3),
            "within_1_bucket": round(within1 / len(labelled), 3),
            "mean_abs_bucket_error": round(mae, 2),
        }
    return summary


def _to_markdown(summary):
    L = [f"# Skin report — {summary['dataset']}", "",
         f"- images read: **{summary['n_images_read']}**",
         f"- skin extractor: `{', '.join(summary['skin_extractor'])}`"
         + ("  ⚠ PIL proxy is coarse — rerun with cv2/mediapipe for real validation"
            if "pil-proxy" in summary["skin_extractor"] else ""),
         f"- Monk continuous mean / median: **{summary['monk_continuous_mean']}** / {summary['monk_continuous_median']}",
         f"- needs_confirm rate: **{summary['needs_confirm_rate']}**   ·   off-swatch rate: **{summary['off_swatch_rate']}**",
         f"- ΔE2000 to nearest swatch — mean: {summary['delta_e_mean']}, p90: {summary['delta_e_p90']}",
         "", "## Monk bucket distribution", ""]
    for k, v in summary["monk_bucket_counts"].items():
        L.append(f"- MST {k}: {v}")
    if "labelled" in summary:
        lb = summary["labelled"]
        L += ["", "## Agreement vs labels (calibration)", "",
              f"- labelled images: {lb['n']}",
              f"- exact bucket agreement: **{lb['exact_bucket_agreement']}**",
              f"- within ±1 bucket: **{lb['within_1_bucket']}**",
              f"- mean abs bucket error: {lb['mean_abs_bucket_error']}"]
    L += ["", "_Generated by bench/skin_report.py — see docs/skin_data_plan.md._"]
    return "\n".join(L)


def run_report(data_dir, name="dataset", out_dir="data/reports", limit=None):
    from app import monk
    rows, methods = [], set()
    for i, (path, label) in enumerate(_iter_images(data_dir)):
        if limit and i >= limit:
            break
        try:
            samples, method = image_to_skin_rgbs(path)
        except Exception:
            continue
        methods.add(method)
        if not samples:
            continue
        rec = monk.classify(samples)
        rows.append({"path": path, "label": label, "value": rec["value"],
                     "monk_continuous": rec["monk_continuous"], "delta_e": rec["delta_e"],
                     "confidence": rec["confidence"], "needs_confirm": rec["needs_confirm"]})
    summary = _summarize(rows, name, sorted(methods))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{name}.json"), "w") as f:
        json.dump(summary, f, indent=2)
    with open(os.path.join(out_dir, f"{name}.md"), "w") as f:
        f.write(_to_markdown(summary) + "\n")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Krey skin-tone validation/calibration report.")
    ap.add_argument("--data", required=True, help="dataset folder (flat or ImageFolder-by-Monk-bucket)")
    ap.add_argument("--name", default="dataset", help="report name (writes data/reports/<name>.{json,md})")
    ap.add_argument("--out", default="data/reports", help="output dir for the report")
    ap.add_argument("--limit", type=int, default=None, help="cap images (quick pass)")
    a = ap.parse_args(argv)
    s = run_report(a.data, name=a.name, out_dir=a.out, limit=a.limit)
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
