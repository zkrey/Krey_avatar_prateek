# Local CatVTON render — clean install (version-locked)

**Goal:** get **one** generative try-on render on Sohan's RTX 3060 (6 GB), then measure
GPU-seconds. This is proving **Path B / Service B** (see `render_approaches.md`) — it is
**not** wired to our code yet.

---

## Why this rewrite (read first — this is the whole point)

The last attempt died on a **version deadlock**, not a normal bug:

- The **ComfyUI CatVTON node** pulls the *rolling-release* ComfyUI, whose new backend
  (`comfy_kitchen`) needs **torch ≥ 2.5**.
- The **AutoMasker** inside CatVTON needs **detectron2 v0.6** (DensePose), which builds
  against **old torch (~2.1)**.
- No single torch satisfies both → `infer_schema ... kernel_size has unsupported type
  list[int]` on one side, or detectron2 won't build on the other. Unwinnable **in that
  combo.**

**The fix: drop the ComfyUI node. Run the authors' own standalone CatVTON app instead.**
It needs the *same* detectron2 — but it has **no ComfyUI**, so the torch ≥ 2.5 demand
disappears. And the CatVTON authors publish **one exact, self-consistent version island**
that detectron2 also builds against. Pin that island and nothing can mismatch.

### The version island (single source of truth — do not deviate)

| Package | Version | Why locked |
|---|---|---|
| **Python** | **3.10** | torch 2.1.2 + detectron2 v0.6 both have/​build wheels here |
| **CUDA Toolkit** (nvcc) | **12.1** | must match torch's `cu121` to compile detectron2 |
| **torch** | **2.1.2** (`+cu121`) | CatVTON authors' pin |
| **torchvision** | **0.16.2** (`+cu121`) | matched to torch 2.1.2 |
| **xformers** | **0.0.23.post1** | built for torch 2.1.2 (memory saver for 6 GB) |
| **detectron2** | **v0.6** (from source) | DensePose for AutoMasker |
| **diffusers** | 0.29.2 | CatVTON pin |
| **transformers** | 4.27.3 | CatVTON pin |
| **accelerate** | 0.31.0 | CatVTON pin |
| **huggingface_hub** | 0.23.4 | CatVTON pin |
| **numpy** | 1.26.4 | < 2.0, required by this torch |
| **opencv-python** | 4.10.0.84 | CatVTON pin |
| **gradio** | 4.39.0 | the demo UI |

**Install order matters:** torch **first** → detectron2 **second** (it needs torch present
to compile) → everything else **last**. Do **not** let a later `pip install` upgrade torch.

> **RTX 3060 = Ampere = compute capability 8.6.** We set `TORCH_CUDA_ARCH_LIST=8.6` so
> detectron2 compiles only the kernel we need (faster build, no guessing).

---

## Recommended: Ubuntu (native **or** WSL2 on Windows 11)

detectron2 builds **cleanly on Linux**. If you're on Windows 11, **WSL2 Ubuntu is the
reliable route** — same steps below. (The Windows-native sheet further down works too, but
detectron2 native on Windows is the hard path.)

### Phase 0 — system prerequisites (once)

```bash
# --- If on WSL2: run `wsl` first, then everything below is inside Ubuntu ---

sudo apt update
sudo apt install -y build-essential git wget ninja-build \
  software-properties-common libgl1 libglib2.0-0

# Python 3.10 (deadsnakes)
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3.10-dev

# CUDA Toolkit 12.1 (nvcc) — needed to BUILD detectron2. The GPU DRIVER is separate
# and already provided by Windows (WSL) or your existing install; do NOT install a
# driver inside WSL. This installs only the compiler toolkit.
wget https://developer.download.nvidia.com/compute/cuda/12.1.0/local_installers/cuda_12.1.0_530.30.02_linux.run
sudo sh cuda_12.1.0_530.30.02_linux.run --toolkit --silent --override
# ^ if the .run complains, use the apt method:
#   https://developer.nvidia.com/cuda-12-1-0-download-archive  (choose deb/network)

# Point the build at CUDA 12.1
echo 'export CUDA_HOME=/usr/local/cuda-12.1'                >> ~/.bashrc
echo 'export PATH=$CUDA_HOME/bin:$PATH'                     >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc

nvidia-smi        # should list the RTX 3060 (proves driver/GPU visible)
nvcc --version    # should say "release 12.1" (proves toolkit for the build)
```

### Phase 1 — the CatVTON repo + a clean venv

```bash
cd ~
git clone https://github.com/Zheng-Chong/CatVTON.git
cd CatVTON

python3.10 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

### Phase 2 — torch FIRST (the island's foundation)

```bash
pip install torch==2.1.2 torchvision==0.16.2 --index-url https://download.pytorch.org/whl/cu121
pip install xformers==0.0.23.post1

# Sanity: torch must see the GPU before we build anything against it
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"
# expect:  2.1.2+cu121 True 12.1
```

If `torch.cuda.is_available()` is **False**, stop — fix that first (driver/WSL GPU
passthrough). Building detectron2 against a CPU-only torch is pointless.

### Phase 3 — detectron2 v0.6 + DensePose SECOND (needs torch present)

```bash
export TORCH_CUDA_ARCH_LIST=8.6      # RTX 3060 = Ampere
export MAX_JOBS=4                     # keep the build from OOM-ing on a laptop

pip install ninja
pip install "git+https://github.com/facebookresearch/detectron2.git@v0.6"
pip install "git+https://github.com/facebookresearch/detectron2.git@v0.6#subdirectory=projects/DensePose"

# Sanity
python -c "import detectron2, densepose; print('detectron2 OK')"
```

> If the **v0.6 tag fails to compile against torch 2.1.2** (rare, but the c10 API moved),
> the community-tested fallback is detectron2 **main** — it keeps the same DensePose API:
> `pip install "git+https://github.com/facebookresearch/detectron2.git"` and the DensePose
> line with the same repo (drop `@v0.6`). Try v0.6 first.

### Phase 4 — the rest of CatVTON's pins LAST (must not touch torch)

```bash
pip install \
  diffusers==0.29.2 transformers==4.27.3 accelerate==0.31.0 huggingface_hub==0.23.4 \
  numpy==1.26.4 opencv-python==4.10.0.84 pillow==10.3.0 scipy==1.13.1 \
  scikit-image==0.24.0 matplotlib==3.9.1 tqdm==4.66.4 PyYAML==6.0.1 \
  gradio==4.39.0 av fvcore cloudpickle omegaconf pycocotools

# Guard: confirm torch was NOT bumped by the line above
python -c "import torch; assert torch.__version__.startswith('2.1.2'), torch.__version__; print('torch still', torch.__version__)"
```

> **Do NOT** run CatVTON's raw `requirements.txt` — it pins `setuptools==51.0.0`, which is
> ancient and breaks modern pip builds. The list above is that file minus that footgun and
> minus the torch/detectron2 lines we already pinned by hand.

### Phase 5 — run the demo

```bash
CUDA_VISIBLE_DEVICES=0 python app.py \
  --output_dir="resource/demo/output" \
  --mixed_precision="bf16" \
  --allow_tf32
```

Model weights (CatVTON + SD-inpainting + DensePose + SCHP) **auto-download from
HuggingFace on first run** (a few GB — one time). Then open the local gradio URL it prints,
upload a **person photo** + a **garment product image** (flat-lay / on-model — **not** a
sewing pattern), pick "upper", and hit run.

---

## Windows 11 native (only if you refuse WSL2 — this is the hard path)

Everything is identical **except** detectron2 must compile with MSVC instead of gcc.
Honest warning: native-Windows detectron2 fails for most people on the first try; **WSL2
above is genuinely easier.** If you still want native:

### Phase 0 — system prerequisites

1. **Python 3.10** — install from python.org (tick "Add to PATH"). Verify: `py -3.10 --version`.
2. **Visual Studio Build Tools 2022** — installer → check **"Desktop development with C++"**
   (this gives `cl.exe`, the C++ compiler detectron2 needs).
3. **CUDA Toolkit 12.1** — from
   https://developer.nvidia.com/cuda-12-1-0-download-archive (this gives `nvcc.exe`).
   The GPU **driver** you already have; this is just the compiler toolkit.

Then **open the "x64 Native Tools Command Prompt for VS 2022"** (Start menu) — use *that*
prompt for everything below, so `cl.exe` is on PATH.

### Phase 1–2 — repo, venv, torch first

```bat
cd %USERPROFILE%
git clone https://github.com/Zheng-Chong/CatVTON.git
cd CatVTON

py -3.10 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel

pip install torch==2.1.2 torchvision==0.16.2 --index-url https://download.pytorch.org/whl/cu121
pip install xformers==0.0.23.post1

python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"
:: expect  2.1.2+cu121 True 12.1
```

### Phase 3 — detectron2 (the Windows-hard part)

```bat
set DISTUTILS_USE_SDK=1
set CUDA_HOME=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1
set TORCH_CUDA_ARCH_LIST=8.6
set MAX_JOBS=4

pip install ninja
pip install "git+https://github.com/facebookresearch/detectron2.git@v0.6"
pip install "git+https://github.com/facebookresearch/detectron2.git@v0.6#subdirectory=projects/DensePose"

python -c "import detectron2, densepose; print('detectron2 OK')"
```

If it errors on a `.cu` file (common on Windows), that's the detectron2-on-Windows wall.
**Switch to WSL2** (the Ubuntu sheet) — that's the pragmatic call, not a defeat.

### Phase 4–5 — same as Ubuntu

Run the identical Phase 4 `pip install` block, then:

```bat
set CUDA_VISIBLE_DEVICES=0
python app.py --output_dir="resource/demo/output" --mixed_precision="bf16" --allow_tf32
```

---

## 6 GB VRAM notes (RTX 3060 Laptop)

- `--mixed_precision="bf16"` → ~8 GB ideal, but works on 6 GB at **768×576** or lower.
- If you hit **CUDA out of memory**: lower the output resolution first; xformers (installed)
  already cuts attention memory. Close other GPU apps (browsers, games).
- First render is slow (model load + download). **Measure the *second* render** for a fair
  GPU-seconds number — that's the number we care about for cost.

---

## If the detectron2 build fights you — push through (don't switch tools)

detectron2 is the one genuinely hard step. **The goal is to complete this build**, so when
it errors, work the fix below — don't reach for a different engine. These are the failures
that actually happen and the fix for each:

- **Builds, but CUDA isn't used / it runs on CPU** → `CUDA_HOME` wasn't set when it compiled.
  Confirm `echo $CUDA_HOME` = `/usr/local/cuda-12.1` and `nvcc --version` = 12.1, then
  reinstall the detectron2 lines with `--force-reinstall --no-build-isolation`.
- **`nvcc fatal: Unsupported gpu architecture`** → the arch flag is missing. Make sure
  `export TORCH_CUDA_ARCH_LIST=8.6` (RTX 3060 = Ampere) is set **in the same shell** before
  the pip install, then retry.
- **C++ compile error (`identifier undefined`, ABI/`c10` mismatch)** → the **v0.6 tag**
  choking on torch 2.1. Switch to detectron2 **main** — it keeps the exact DensePose API
  CatVTON imports, so this is still the same fix, just a newer compiler front-end:
  ```bash
  pip install "git+https://github.com/facebookresearch/detectron2.git"
  pip install "git+https://github.com/facebookresearch/detectron2.git#subdirectory=projects/DensePose"
  ```
- **Build killed / OOM on the laptop** → lower parallelism: `export MAX_JOBS=2` and retry.
- **`No module named 'torch'` during the build** → torch wasn't installed first, or a
  different Python/venv is active. Re-activate the venv, redo Phase 2, then Phase 3.

Between the pinned island (torch 2.1.2 + CUDA 12.1 + arch 8.6) and the `main`-branch
fallback, this build **does** go through on Linux. Stay on it — WSL2 is the reliable route.

---

## Once it renders — log the GPU-seconds

Read the wall-clock seconds the CatVTON app prints, **skip the first render** (it includes
model load/download), and log the rest into our benchmark so the local number sits
apples-to-apples next to the cloud IDM-VTON figure (~16.6 GPU-s ≈ ₹1.6):

```bash
python -m bench.gpu_benchmark --provider local --model catvton-rtx3060 \
    --latencies "20.0,12.0,11.8,11.9" --out bench_catvton_local.json
```

Details in `bench/README.md` → "Log a LOCAL render".
