# Krey render benchmark — Google Colab runner  (free T4 GPU)
# ---------------------------------------------------------------------------
# Paste each `# %%` block into a Colab cell (Runtime -> Change runtime type -> T4 GPU).
# It proves whether a generative try-on keeps the user recognisably themselves, for $0.
# The model is CatVTON (light, fits a free T4). The one model-specific call (run_tryon)
# is filled from CatVTON's own app.py (zhengchong/CatVTON) — verify against the current
# README if the repo has moved. Plan: docs/render_benchmark_plan.md
# ===========================================================================

# %% [markdown]
# ## 0. Confirm we have a GPU (need a T4 or better)

# %%
import subprocess
print(subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout or "NO GPU — Runtime->Change runtime type->T4 GPU")

# %% [markdown]
# ## 1. Get Krey's scorer (reuses our real ArcFace recognition)
# Clone the repo so `bench/render_eval.py` + `app/identity.py` are importable. Private repo:
# upload the two files manually, or paste a token into the clone URL when prompted.

# %%
import os, sys
!pip -q install insightface onnxruntime opencv-python-headless pillow numpy
# Private repo — upload app/ + bench/ manually, OR clone with a token:
# !git clone https://<TOKEN>@github.com/zkrey/krey_avatar_prateek.git
KREY_REPO = "/content/krey_avatar_prateek"          # adjust to your clone/upload path
sys.path.insert(0, KREY_REPO)
os.environ["KREY_FACE_MODEL"] = "buffalo_l"          # Colab has the RAM — use the accurate model

# %% [markdown]
# ## 2. Install CatVTON + its mask stack
# CatVTON is a light SD-inpainting try-on that fits a free T4 in fp16. Its AutoMasker uses
# DensePose (detectron2) + SCHP; the CatVTON checkpoint repo bundles both, but detectron2
# must be installed separately and takes a few minutes. Verify against the current CatVTON
# README (repos move): https://github.com/Zheng-Chong/CatVTON

# %%
%cd /content
!git clone https://github.com/Zheng-Chong/CatVTON.git
%cd /content/CatVTON
!pip -q install -r requirements.txt
# detectron2 (DensePose backbone for AutoMasker) — build for the current torch/cuda:
!pip -q install 'git+https://github.com/facebookresearch/detectron2.git'
sys.path.insert(0, "/content/CatVTON")               # so `model.*` and `utils` import

# %% [markdown]
# ## 3. Build the pipeline ONCE, then the model call
# Faithful to CatVTON's app.py. fp16 for the T4 (it has no bf16). The checkpoint,
# DensePose and SCHP weights all download automatically from `zhengchong/CatVTON`.

# %%
import torch
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
              cloth_type: str = "upper", steps: int = 50, guidance: float = 2.5,
              seed: int = 42) -> str:
    """Render `person` wearing `garment`, save to out_path, return out_path.
    cloth_type is one of AutoMasker's classes: 'upper', 'lower', or 'overall' (dress/full).
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

# %% [markdown]
# ## 4. Test set — (person, garment, cloth_type) triples
# Upload a few person photos + garment images to Colab (left file panel), list them here.
# Use 5–10: a couple of people x a few garment types. cloth_type must match the garment:
#   'upper' = tee/shirt/top · 'lower' = trousers/skirt · 'overall' = dress/jumpsuit.

# %%
PAIRS = [
    # (person_image, garment_image, cloth_type)
    # ("/content/people/priya_1.jpg", "/content/garments/white_tee.jpg",  "upper"),
    # ("/content/people/priya_1.jpg", "/content/garments/blue_dress.jpg", "overall"),
]
OUT_DIR = "/content/krey_renders"; os.makedirs(OUT_DIR, exist_ok=True)

# %% [markdown]
# ## 5. Run + score every pair (identity preserved? how fast?)

# %%
import time
from bench.render_eval import identity_similarity, RECOGNISABLE_COSINE

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

print(f"{'person':22} {'garment':18} {'id_cos':>7} {'secs':>6}  verdict")
for r in rows:
    print(f"{r[0]:22} {r[1]:18} {str(r[2]):>7} {str(r[3]):>6}  {r[4]}")

ok = [r for r in rows if r[2] is not None]
if ok:
    import statistics
    print(f"\nmean identity cosine = {statistics.mean(r[2] for r in ok):.3f}  "
          f"(floor {RECOGNISABLE_COSINE}) · mean {statistics.mean(r[3] for r in ok):.1f}s/render")
print("\nAlso eyeball each render in", OUT_DIR, "for garment fidelity (colour/cut/print).")

# %% [markdown]
# ## 6. Read the result
# PASS bar (docs/render_benchmark_plan.md): identity cosine stays high across the set AND the
# garment is clearly right AND render time is tolerable on a free/cheap GPU.
# - Passes -> wrap run_tryon as a Modal serverless-GPU endpoint (free credits) and wire /render
#   behind the existing canRender gate.
# - Fails on identity -> try IDM-VTON (Colab Pro/A100) or a different model before deciding.
