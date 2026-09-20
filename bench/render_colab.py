# Krey render benchmark — Google Colab runner  (free T4 GPU)
# ---------------------------------------------------------------------------
# Paste each `# %%` block into a Colab cell (Runtime -> Change runtime type -> T4 GPU),
# or open bench/render_colab.ipynb straight from GitHub and Run all.
# It proves whether a generative try-on (CatVTON) keeps the user recognisably themselves,
# for $0. The scorer is self-contained (no repo checkout needed); the model call (run_tryon)
# is filled from CatVTON's own app.py. Plan: docs/render_benchmark_plan.md
#
# HARD-WON NOTES (baked in below so you don't rediscover them):
#  - CatVTON's requirements.txt pins torch==2.4.0, which Colab no longer has. Do NOT let it
#    reinstall torch — keep Colab's torch/CUDA and install everything else.
#  - `av` (PyAV) and detectron2 are needed by the DensePose masker and aren't in the pins.
#  - INPUT MUST BE SINGLE-PERSON, FRONT-ON, ROUGHLY WAIST-UP. Group/party/angled photos
#    score badly because the masker grabs the wrong region and the face is tiny. This is a
#    product finding too: the render-capture UX must enforce a clean single-subject shot.
# ===========================================================================

# %% [markdown]
# ## 0. Confirm we have a GPU (need a T4 or better)

# %%
import subprocess
print(subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout or "NO GPU — Runtime->Change runtime type->T4 GPU")

# %% [markdown]
# ## 1. The identity scorer (self-contained — no repo checkout)
# Uses Krey's real recognition model (InsightFace buffalo_l / ArcFace) to answer the only
# question that matters: after the try-on, is it still recognisably the same person? This is
# the same ArcFace cosine the product uses; inlined here so the benchmark needs nothing but
# InsightFace (buffalo_l downloads once, ~166 MB).

# %%
!pip -q install insightface onnxruntime opencv-python-headless pillow numpy
import cv2, numpy as np
from insightface.app import FaceAnalysis

RECOGNISABLE_COSINE = 0.50          # starting line; recalibrate against tester judgements
_face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
_face_app.prepare(ctx_id=-1, det_size=(640, 640))

def _best_face(img_bgr):
    """Most prominent face in a frame (det_score x area), or None."""
    faces = _face_app.get(img_bgr)
    if not faces:
        return None
    def sc(f):
        x0, y0, x1, y1 = f.bbox
        return f.det_score * max(1, (x1 - x0) * (y1 - y0))
    return max(faces, key=sc)

def identity_similarity(original_path: str, render_path: str) -> float:
    """ArcFace cosine between the original person and the rendered try-on."""
    a, b = cv2.imread(original_path), cv2.imread(render_path)
    if a is None or b is None:
        raise SystemExit("could not read one of the images")
    fa, fb = _best_face(a), _best_face(b)
    if fa is None:
        raise SystemExit("no face found in the ORIGINAL image")
    if fb is None:
        raise SystemExit("no face in the RENDER — the try-on hid/garbled the face")
    ea, eb = fa.normed_embedding, fb.normed_embedding
    return float(np.dot(ea, eb) / (np.linalg.norm(ea) * np.linalg.norm(eb) + 1e-9))

print("scorer ready · floor =", RECOGNISABLE_COSINE)

# %% [markdown]
# ## 2. Install CatVTON + its mask stack
# Keep Colab's torch/CUDA (strip CatVTON's torch pin); add PyAV + detectron2 (DensePose
# backbone) which aren't in the pins. detectron2 builds from source — a few minutes.
# Verify against the current CatVTON README if it has moved: https://github.com/Zheng-Chong/CatVTON

# %%
import os, sys
!git clone https://github.com/Zheng-Chong/CatVTON.git /content/CatVTON 2>/dev/null || echo "CatVTON already cloned"
# CatVTON pins torch==2.4.0 (not on Colab). Keep Colab's torch+CUDA; install everything else:
!grep -viE '^(torch|torchvision|torchaudio|gradio|huggingface[-_]hub)' /content/CatVTON/requirements.txt > /tmp/req_notorch.txt
!pip -q install -r /tmp/req_notorch.txt
!pip -q install av                                                 # DensePose video dep, not in pins
!pip -q install 'git+https://github.com/facebookresearch/detectron2.git'
sys.path.insert(0, "/content/CatVTON")                             # so `model.*` and `utils` import
import torch
print("CatVTON deps ready · torch:", torch.__version__, "· CUDA:", torch.cuda.is_available())

# %% [markdown]
# ## 3. Build the pipeline ONCE, then the model call
# Faithful to CatVTON's app.py. fp16 for the T4 (no bf16 on Turing). The checkpoint,
# DensePose and SCHP weights all download automatically from `zhengchong/CatVTON`.

# %%
import os, sys, torch
from PIL import Image
from diffusers.image_processor import VaeImageProcessor
from huggingface_hub import snapshot_download
from model.cloth_masker import AutoMasker
from model.pipeline import CatVTONPipeline
from utils import init_weight_dtype, resize_and_crop, resize_and_padding

W, H = 768, 1024                                       # CatVTON's native try-on resolution
_repo = snapshot_download(repo_id="zhengchong/CatVTON")

_pipeline = CatVTONPipeline(
    base_ckpt="runwayml/stable-diffusion-inpainting",
    attn_ckpt=_repo,
    attn_ckpt_version="mix",
    weight_dtype=init_weight_dtype("fp16"),            # T4 = fp16 (no bf16 on Turing)
    use_tf32=True,
    device="cuda",
)
_mask_processor = VaeImageProcessor(
    vae_scale_factor=8, do_normalize=False, do_binarize=True, do_convert_grayscale=True
)
_automasker = AutoMasker(
    densepose_ckpt=os.path.join(_repo, "DensePose"),
    schp_ckpt=os.path.join(_repo, "SCHP"),
    device="cuda",
)

import cv2
import numpy as np


def smart_crop_box(img_bgr, face_frac: float = 0.20):
    """Face-anchored 3:4 torso box (left, top, w, h), or None if no face.
    Real-world photos are full-body/off-centre → the face ends up tiny and the masker
    grabs the wrong region. Anchoring a head-to-hips crop on the detected face so the face
    fills ~face_frac of the height fixed a real full-body shot from 0.24 -> 0.94 identity.
    Reuses _face_app from the scorer cell — no extra model."""
    faces = _face_app.get(img_bgr)
    if not faces:
        return None
    f = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    x0, y0, x1, y1 = f.bbox
    fh = y1 - y0
    cx = (x0 + x1) / 2.0
    Hc = fh / face_frac
    Wc = 0.75 * Hc                                  # 3:4 to match CatVTON's 768x1024
    top = y0 - 0.15 * Hc                            # a little headroom above the face
    left = cx - Wc / 2.0
    ih, iw = img_bgr.shape[:2]
    Wc = min(Wc, iw); Hc = min(Hc, ih)
    left = 0 if Wc >= iw else max(0.0, min(left, iw - Wc))
    top = 0 if Hc >= ih else max(0.0, min(top, ih - Hc))
    return int(left), int(top), int(Wc), int(Hc)


def run_tryon(person_path: str, garment_path: str, out_path: str,
              cloth_type: str = "upper", steps: int = 40, guidance: float = 2.5,
              seed: int = 42, auto_crop: bool = True, composite: bool = True) -> str:
    """Render `person` wearing `garment`, save to out_path, return out_path.
    auto_crop: face-anchor a torso crop first (makes real-world/full-body photos work).
    composite: paste the rendered torso back into the FULL original (real photo in, real
               photo dressed out). Set composite=False to save just the rendered crop
               (that's the honest per-render identity measure — see the benchmark loop).
    cloth_type: 'upper' | 'lower' | 'overall'. steps=40 ~ good speed/quality on a T4."""
    orig = Image.open(person_path).convert("RGB")
    box = smart_crop_box(cv2.cvtColor(np.array(orig), cv2.COLOR_RGB2BGR)) if auto_crop else None
    src = orig.crop((box[0], box[1], box[0] + box[2], box[1] + box[3])) if box else orig
    person = resize_and_crop(src, (W, H))
    cloth = resize_and_padding(Image.open(garment_path).convert("RGB"), (W, H))
    mask = _automasker(person, cloth_type)["mask"]
    mask = _mask_processor.blur(mask, blur_factor=9)
    generator = torch.Generator(device="cuda").manual_seed(seed) if seed != -1 else None
    result = _pipeline(
        image=person, condition_image=cloth, mask=mask,
        num_inference_steps=steps, guidance_scale=guidance, generator=generator,
    )[0]
    if composite and box:
        l, t, wc, hc = box
        # mask-aware composite: swap ONLY the garment-mask pixels back into the full photo, so
        # face/hands/background stay the real originals (fixes generative-model hand artifacts).
        m = (mask.convert("L") if hasattr(mask, "convert")
             else Image.fromarray(np.asarray(mask)).convert("L")).resize((wc, hc))
        base = orig.crop((l, t, l + wc, t + hc)).convert("RGB")
        comp = Image.composite(result.resize((wc, hc)), base, m)
        canvas = orig.copy()
        canvas.paste(comp, (l, t))
        canvas.save(out_path)
    else:
        result.save(out_path)
    return out_path


def crop_for_score(person_path: str, out_path: str) -> str:
    """Save the same face-anchored crop run_tryon uses, so the benchmark scores like-for-like
    (crop identity vs rendered-crop identity), not a tiny full-frame face vs a large one."""
    orig = Image.open(person_path).convert("RGB")
    box = smart_crop_box(cv2.cvtColor(np.array(orig), cv2.COLOR_RGB2BGR))
    (orig.crop((box[0], box[1], box[0] + box[2], box[1] + box[3])) if box else orig).save(out_path)
    return out_path

print("pipeline ready · run_tryon(person, garment, out, cloth_type=..., auto_crop=True, composite=True)")

# %% [markdown]
# ## 4. Test set — (person, garment, cloth_type) triples
# Upload SINGLE-PERSON, front-on, waist-up photos of yourself (left file panel). Pair each
# with a garment. CatVTON ships example garments under /content/CatVTON/resource/demo/example/
# condition/{upper,overall}/ — list them with the helper, or upload your own.
# cloth_type: 'upper' = tee/shirt/top · 'lower' = trousers/skirt · 'overall' = dress/jumpsuit.

# %%
import glob
print("CatVTON example garments you can use:")
for p in sorted(glob.glob("/content/CatVTON/resource/demo/example/condition/upper/*")
              + glob.glob("/content/CatVTON/resource/demo/example/condition/overall/*")):
    print("  ", p)
print("\nyour uploaded photos:")
for p in sorted(glob.glob("/content/*.jpg")+glob.glob("/content/*.jpeg")+glob.glob("/content/*.png")):
    print("  ", p)

PAIRS = [
    # (your_photo, garment_image, cloth_type)  — fill from the lists printed above
    # ("/content/me.jpg", "/content/CatVTON/resource/demo/example/condition/upper/22790049_53294275_1000.jpg", "upper"),
]

# %% [markdown]
# ## 5. Run + score every pair (identity preserved? how fast?)

# %%
import time, os, statistics

OUT_DIR = "/content/krey_renders"; os.makedirs(OUT_DIR, exist_ok=True)

rows = []
for i, (person, garment, ctype) in enumerate(PAIRS):
    render = os.path.join(OUT_DIR, f"tryon_{i}.png")           # rendered crop (for the honest score)
    full = os.path.join(OUT_DIR, f"tryon_{i}_full.png")        # dressed FULL photo (for eyeballing)
    t0 = time.time()
    try:
        # face-anchored crop makes real-world/full-body photos work (0.24 -> 0.94 on a real shot)
        crop = crop_for_score(person, os.path.join(OUT_DIR, f"crop_{i}.jpg"))
        run_tryon(person, garment, render, cloth_type=ctype, auto_crop=True, composite=False)
        run_tryon(person, garment, full, cloth_type=ctype, auto_crop=True, composite=True)
        secs = time.time() - t0
        sim = identity_similarity(crop, render)               # like-for-like: crop vs rendered crop
        rows.append((os.path.basename(person), os.path.basename(garment), round(sim, 3),
                     round(secs, 1), "PASS" if sim >= RECOGNISABLE_COSINE else "FAIL"))
    except Exception as e:
        rows.append((os.path.basename(person), os.path.basename(garment), None, None, f"ERROR: {e}"))

print(f"{'person':28} {'garment':22} {'id_cos':>7} {'secs':>6}  verdict")
for r in rows:
    print(f"{r[0]:28} {r[1]:22} {str(r[2]):>7} {str(r[3]):>6}  {r[4]}")

ok = [r for r in rows if r[2] is not None]
if ok:
    print(f"\nmean identity cosine = {statistics.mean(r[2] for r in ok):.3f}  "
          f"(floor {RECOGNISABLE_COSINE}) · mean {statistics.mean(r[3] for r in ok):.1f}s/render")
print("\nSaved in", OUT_DIR, ": tryon_*.png (rendered crop, scored) and tryon_*_full.png "
      "(your FULL photo dressed — real photo in, real photo out). Eyeball garment fidelity on both.")

# %% [markdown]
# ## 6. Read the result
# PASS bar (docs/render_benchmark_plan.md): identity cosine stays high across the set AND the
# garment is clearly right AND render time is tolerable on a free/cheap GPU.
# - smart_crop makes REAL-WORLD photos work: a full-body arms-out shot went 0.24 -> 0.94 just by
#   face-anchoring the crop. CatVTON only inpaints the masked garment region, so face/background/
#   hair pass through untouched — most "noise" (background, on-face skin/texture) needs no fix.
# - What DOES need handling, measure-first (ablation): face size (solved by smart_crop), pose
#   (torso crop helps), lighting/white-balance + face-restore only if a test moves the score.
# - Passes -> deploy render/modal_app.py (Modal serverless GPU) and wire /render behind the
#   existing canRender gate (render/README.md).
