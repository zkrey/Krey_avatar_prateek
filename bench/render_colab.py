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

def run_tryon(person_path: str, garment_path: str, out_path: str,
              cloth_type: str = "upper", steps: int = 40, guidance: float = 2.5,
              seed: int = 42) -> str:
    """Render `person` wearing `garment`, save to out_path, return out_path.
    cloth_type is one of AutoMasker's classes: 'upper', 'lower', or 'overall' (dress/full).
    steps=40 is a good speed/quality point on a T4 (~90s); raise toward 50 for max quality.
    """
    person = resize_and_crop(Image.open(person_path).convert("RGB"), (W, H))
    cloth = resize_and_padding(Image.open(garment_path).convert("RGB"), (W, H))
    mask = _automasker(person, cloth_type)["mask"]
    mask = _mask_processor.blur(mask, blur_factor=9)
    generator = torch.Generator(device="cuda").manual_seed(seed) if seed != -1 else None
    result = _pipeline(
        image=person, condition_image=cloth, mask=mask,
        num_inference_steps=steps, guidance_scale=guidance, generator=generator,
    )[0]
    result.save(out_path)
    return out_path

print("pipeline ready · run_tryon(person, garment, out, cloth_type='upper'|'lower'|'overall')")

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
    out = os.path.join(OUT_DIR, f"tryon_{i}.png")
    t0 = time.time()
    try:
        run_tryon(person, garment, out, cloth_type=ctype)
        secs = time.time() - t0
        sim = identity_similarity(person, out)           # our real ArcFace "is it still them?"
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
print("\nRenders saved in", OUT_DIR, "— open them to check garment fidelity (colour/cut/print).")

# %% [markdown]
# ## 6. Read the result
# PASS bar (docs/render_benchmark_plan.md): identity cosine stays high across the set AND the
# garment is clearly right AND render time is tolerable on a free/cheap GPU.
# - A LOW score with a group/angled input = input problem, not model: re-test single-person,
#   front-on, waist-up (this is the capture spec the product must enforce).
# - Passes on clean inputs -> wrap run_tryon as a Modal serverless-GPU endpoint (free credits)
#   and wire /render behind the existing canRender gate.
# - Fails on identity even on clean inputs -> try IDM-VTON (Colab Pro/A100) before deciding.
