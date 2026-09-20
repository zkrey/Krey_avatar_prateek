# Krey render benchmark — Kaggle Notebook runner  (free T4 GPU, separate quota from Colab)
# ---------------------------------------------------------------------------
# Same CatVTON try-on benchmark as render_colab.py, adapted for Kaggle Notebooks.
# Why Kaggle: 30 hrs/week of free T4/P100 on a DIFFERENT quota than Colab — so when Colab
# throttles you, come here instead. Plan: docs/render_benchmark_plan.md
#
# ONE-TIME KAGGLE SETUP (do these in the notebook UI before running):
#  1. Account must be PHONE-VERIFIED (Settings -> Phone verification) — required for GPU + internet.
#  2. Right sidebar -> Settings:
#       - Accelerator: GPU T4 x2  (or P100)
#       - Internet: On            (needed for pip + HuggingFace weight downloads)
#  3. Add your test photos: right sidebar -> Input -> "Upload" -> create a Dataset from your
#     selfies. They mount read-only at /kaggle/input/<your-dataset-name>/...
#
# Kaggle vs Colab differences baked in below: writable dir is /kaggle/working (not /content);
# your uploaded photos live under /kaggle/input/ (read-only). Everything else is identical.
# ===========================================================================

# %% [markdown]
# ## 0. Confirm we have a GPU
# If this errors with 'nvidia-smi not found', the accelerator isn't on:
# right sidebar -> Settings -> Accelerator -> GPU T4 x2, then re-run.

# %%
import shutil, subprocess
print(subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout
      if shutil.which("nvidia-smi") else "NO GPU — Settings (right sidebar) -> Accelerator -> GPU T4 x2")

# %% [markdown]
# ## 1. The identity scorer (self-contained — no repo checkout)
# Krey's real recognition model (InsightFace buffalo_l / ArcFace). Answers the only question that
# matters: after the try-on, is it still recognisably the same person? buffalo_l downloads once.

# %%
!pip -q install insightface onnxruntime opencv-python-headless pillow numpy
import cv2, numpy as np
from insightface.app import FaceAnalysis

RECOGNISABLE_COSINE = 0.50
_face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
_face_app.prepare(ctx_id=-1, det_size=(640, 640))

def _best_face(img_bgr):
    faces = _face_app.get(img_bgr)
    if not faces:
        return None
    def sc(f):
        x0, y0, x1, y1 = f.bbox
        return f.det_score * max(1, (x1 - x0) * (y1 - y0))
    return max(faces, key=sc)

def identity_similarity(original_path: str, render_path: str) -> float:
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
# Keep Kaggle's torch/CUDA (strip CatVTON's torch pin); add PyAV + detectron2 (DensePose
# backbone). detectron2 builds from source (a few minutes). Needs Internet: On.

# %%
import os, sys
CAT = "/kaggle/working/CatVTON"
!git clone https://github.com/Zheng-Chong/CatVTON.git {CAT} 2>/dev/null || echo "CatVTON already cloned"
# CatVTON pins torch==2.4.0 (not on Kaggle). Keep Kaggle's torch+CUDA; install everything else:
!grep -viE '^(torch|torchvision|torchaudio)' {CAT}/requirements.txt > /kaggle/working/req_notorch.txt
!pip -q install -r /kaggle/working/req_notorch.txt
!pip -q install av                                                 # DensePose video dep, not in pins
!pip -q install 'git+https://github.com/facebookresearch/detectron2.git'
sys.path.insert(0, CAT)                                            # so `model.*` and `utils` import
import torch
print("CatVTON deps ready · torch:", torch.__version__, "· CUDA:", torch.cuda.is_available())

# %% [markdown]
# ## 3. Build the pipeline ONCE, then the model call
# Faithful to CatVTON's app.py. fp16 for the T4 (no bf16 on Turing). Checkpoint + DensePose +
# SCHP weights auto-download from `zhengchong/CatVTON` (needs Internet: On).

# %%
import os, sys, torch
from PIL import Image
from diffusers.image_processor import VaeImageProcessor
from huggingface_hub import snapshot_download
from model.cloth_masker import AutoMasker
from model.pipeline import CatVTONPipeline
from utils import init_weight_dtype, resize_and_crop, resize_and_padding

W, H = 768, 1024
_repo = snapshot_download(repo_id="zhengchong/CatVTON")

_pipeline = CatVTONPipeline(
    base_ckpt="runwayml/stable-diffusion-inpainting",
    attn_ckpt=_repo,
    attn_ckpt_version="mix",
    weight_dtype=init_weight_dtype("fp16"),
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
    """Render `person` wearing `garment`. cloth_type: 'upper'|'lower'|'overall'."""
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
# Your uploaded photos are under /kaggle/input/ (read-only, from the Dataset you added).
# CatVTON ships example garments in the clone. The helper lists both — fill PAIRS from them.
# Use SINGLE-PERSON, front-on, waist-up photos. cloth_type: upper / lower / overall.

# %%
import glob
print("CatVTON example garments:")
for p in sorted(glob.glob(CAT + "/resource/demo/example/condition/upper/*")
              + glob.glob(CAT + "/resource/demo/example/condition/overall/*")):
    print("  ", p)
print("\nyour uploaded photos (from /kaggle/input):")
for p in sorted(glob.glob("/kaggle/input/**/*.jpg", recursive=True)
              + glob.glob("/kaggle/input/**/*.jpeg", recursive=True)
              + glob.glob("/kaggle/input/**/*.png", recursive=True)):
    print("  ", p)

PAIRS = [
    # (your_photo, garment_image, cloth_type)  — fill from the lists printed above
    # ("/kaggle/input/my-selfies/me.jpg", CAT + "/resource/demo/example/condition/upper/22790049_53294275_1000.jpg", "upper"),
]

# %% [markdown]
# ## 5. Run + score every pair (identity preserved? how fast?)

# %%
import time, os, statistics

OUT_DIR = "/kaggle/working/krey_renders"; os.makedirs(OUT_DIR, exist_ok=True)

rows = []
for i, (person, garment, ctype) in enumerate(PAIRS):
    out = os.path.join(OUT_DIR, f"tryon_{i}.png")
    t0 = time.time()
    try:
        run_tryon(person, garment, out, cloth_type=ctype)
        secs = time.time() - t0
        sim = identity_similarity(person, out)
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
print("\nRenders saved in", OUT_DIR, "— open the Output/Data panel to view them.")

# %% [markdown]
# ## 6. Read the result
# Same bar as the Colab plan (docs/render_benchmark_plan.md): identity cosine stays high AND the
# garment is clearly right AND render time is tolerable. Low score on a group/angled input = input
# problem, not model (re-test single-person, front-on, waist-up). Passes -> Modal endpoint behind
# the canRender gate.
