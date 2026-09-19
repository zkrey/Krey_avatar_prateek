# Krey render benchmark — Google Colab runner  (free T4 GPU)
# ---------------------------------------------------------------------------
# Paste each `# %%` block into a Colab cell (Runtime -> Change runtime type -> T4 GPU).
# It proves whether a generative try-on keeps the user recognisably themselves, for $0.
# The pair-loop, output saving, scoring and report are complete and correct; the ONE
# model-specific call (run_tryon) is marked — fill it from the chosen model's current
# README so we never depend on a stale API guess. Plan: docs/render_benchmark_plan.md
# ===========================================================================

# %% [markdown]
# ## 0. Confirm we have a GPU

# %%
import subprocess
print(subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout or "NO GPU — set Runtime->GPU")

# %% [markdown]
# ## 1. Get Krey's scorer (reuses our real ArcFace recognition)
# Clone the repo so `bench/render_eval.py` + `app/identity.py` are importable. Private repo:
# paste a token when prompted, or upload the two files manually.

# %%
import os
!pip -q install insightface onnxruntime opencv-python-headless pillow numpy
# clone (public) or upload app/ + bench/ manually if private:
# !git clone https://github.com/zkrey/krey_avatar_prateek.git && cd krey_avatar_prateek
os.environ["KREY_FACE_MODEL"] = "buffalo_l"   # Colab has the RAM — use the accurate model
import sys; sys.path.insert(0, "/content/krey_avatar_prateek")  # adjust to the clone path

# %% [markdown]
# ## 2. Install the try-on model
# Start with **CatVTON** (light, fits a free T4). Follow its README for the exact install +
# weight download. Alternates: OOTDiffusion (T4-tight), IDM-VTON (best, needs A100/Colab Pro).

# %%
# Example (VERIFY against the current CatVTON README — repos move):
# !git clone https://github.com/Zheng-Chong/CatVTON.git
# %cd CatVTON
# !pip -q install -r requirements.txt
# weights download per the README / HuggingFace model card.

# %% [markdown]
# ## 3. THE model call — fill this from the model's README inference example
# Input: a person image + a garment image. Output: path to the rendered try-on image.
# Keep the signature; drop the model's own inference inside. This is the only model-specific
# part — everything below is model-agnostic.

# %%
def run_tryon(person_path: str, garment_path: str, out_path: str) -> str:
    """Render `person` wearing `garment`, save to out_path, return out_path.
    >>> FILL from CatVTON/OOTDiffusion/IDM-VTON README (load pipeline once, then infer). <<<
    """
    raise NotImplementedError("drop the chosen model's inference here")

# %% [markdown]
# ## 4. Test set — person x garment pairs
# Upload a few person photos + garment images to Colab (left panel), list the pairs here.
# Use 5-10 pairs: a couple of people x a few garment types (tee / shirt / dress).

# %%
PAIRS = [
    # (person_image, garment_image)
    # ("/content/people/priya_1.jpg", "/content/garments/white_tee.jpg"),
]
OUT_DIR = "/content/krey_renders"; os.makedirs(OUT_DIR, exist_ok=True)

# %% [markdown]
# ## 5. Run + score every pair (identity preserved? how fast?)

# %%
import time, cv2
from bench.render_eval import identity_similarity, RECOGNISABLE_COSINE

rows = []
for i, (person, garment) in enumerate(PAIRS):
    out = os.path.join(OUT_DIR, f"tryon_{i}.png")
    t0 = time.time()
    try:
        run_tryon(person, garment, out)
        secs = time.time() - t0
        sim = identity_similarity(person, out)          # our real ArcFace "is it still them?"
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
