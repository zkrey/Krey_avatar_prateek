"""
Krey render (Service B) — CatVTON virtual try-on as a Modal serverless-GPU endpoint.

SCAFFOLD, pending the benchmark verdict (docs/render_benchmark_plan.md). It wraps the exact
proven CatVTON code from bench/render_colab.py as a scale-to-zero Modal function, so /render
pays only per render (Modal's free monthly credits cover early usage). Nothing here runs until
you deploy it; app/main.py is untouched until the clean-input identity score clears the bar.

DEPLOY
------
    pip install modal
    modal token new                                            # one-time auth (your account)
    modal secret create krey-render KREY_RENDER_SECRET=<long-random-string>
    modal deploy render/modal_app.py
Modal prints a public URL for the `web` app. On Service A (Railway) set:
    KREY_MODAL_RENDER_URL = <that URL>
    KREY_RENDER_SECRET    = <the same long-random-string>
Then wire the /render endpoint (see render/README.md) and deploy Service A.

NOTES
-----
- The Modal API evolves — verify class/decorator names against the current Modal docs if a
  deploy errors (same discipline as the CatVTON API: we track the source, not a memory).
- GPU: T4 is cheapest; L4/A10G are ~2–3x faster per render (better UX, higher $/hr — the
  benchmark's seconds/render feeds this choice). Override with KREY_RENDER_GPU.
- Weights (CatVTON + SD-inpainting + DensePose/SCHP) are baked into the image at build time,
  so containers cold-start without re-downloading ~5 GB.
- Licence: the CatVTON checkpoint is research/non-commercial — fine to validate; swap for (or
  licence) a commercial VTON model before launch.
"""
from __future__ import annotations
import io
import os
import sys

import modal

GPU = os.environ.get("KREY_RENDER_GPU", "T4")      # T4 = free tier (no card). L4/A10G/A100
#                                                    are faster but need a Modal payment method.
CATVTON_DIR = "/opt/CatVTON"
CATVTON_REPO = "zhengchong/CatVTON"
BASE_REPO = "runwayml/stable-diffusion-inpainting"


def _bake_weights():
    """Runs at image BUILD time so runtime containers never download weights/models."""
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=CATVTON_REPO)        # checkpoint + DensePose + SCHP
    snapshot_download(repo_id=BASE_REPO)           # SD-inpainting base
    from insightface.app import FaceAnalysis       # buffalo_l for the face-anchored smart-crop
    FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"]).prepare(ctx_id=-1, det_size=(640, 640))


# CatVTON's requirements.txt no longer resolves (pins diffusers-from-git needing hub>=1.31
# against transformers 4.46.3 needing hub<1.0). So we DON'T use it — we install the exact set
# proven on Kaggle (diffusers 0.29.2 + a compatible, pinned trio), plus torch (Modal's base has
# none, unlike Kaggle), plus the DensePose/insightface stack, then bake all weights/models.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "libgl1", "libglib2.0-0", "libgomp1")
    .run_commands(f"git clone https://github.com/Zheng-Chong/CatVTON.git {CATVTON_DIR}")
    .pip_install(
        "torch", "torchvision",                                   # CUDA wheels for the Modal GPU
        "diffusers==0.29.2", "transformers==4.46.3", "accelerate==0.31.0",
        "huggingface_hub==0.25.2",                                # satisfies diffusers + transformers
        "numpy==1.26.4", "scipy", "opencv-python-headless", "pillow", "matplotlib",
        "tqdm", "pyyaml", "scikit-image", "einops", "av",
        "omegaconf", "pycocotools", "fvcore", "cloudpickle",      # DensePose/detectron2 deps
        "insightface", "onnxruntime",                             # smart-crop face detector
    )
    .run_commands("pip install 'git+https://github.com/facebookresearch/detectron2.git'")
    .run_function(_bake_weights)
)

app = modal.App("krey-render")


@app.cls(gpu=GPU, image=image, timeout=600, scaledown_window=120)
class Renderer:
    """One warm container loads the pipeline once (@enter) and serves many renders."""

    @modal.enter()
    def load(self):
        sys.path.insert(0, CATVTON_DIR)
        import torch
        from diffusers.image_processor import VaeImageProcessor
        from huggingface_hub import snapshot_download
        from insightface.app import FaceAnalysis
        from model.cloth_masker import AutoMasker
        from model.pipeline import CatVTONPipeline
        from utils import init_weight_dtype, resize_and_crop, resize_and_padding

        self._torch = torch
        self._crop = resize_and_crop
        self._pad = resize_and_padding
        self.W, self.H = 768, 1024

        repo = snapshot_download(repo_id=CATVTON_REPO)   # cached in the image; instant
        self.pipe = CatVTONPipeline(
            base_ckpt=BASE_REPO,
            attn_ckpt=repo,
            attn_ckpt_version="mix",
            weight_dtype=init_weight_dtype("fp16"),
            use_tf32=True,
            device="cuda",
            skip_safety_check=True,   # avoids diffusers0.29 vs new-transformers safety-checker clash
        )
        self.mask_proc = VaeImageProcessor(
            vae_scale_factor=8, do_normalize=False, do_binarize=True, do_convert_grayscale=True
        )
        self.masker = AutoMasker(
            densepose_ckpt=os.path.join(repo, "DensePose"),
            schp_ckpt=os.path.join(repo, "SCHP"),
            device="cuda",
        )
        # face detector for the smart-crop (real-world/full-body photos → face-anchored torso crop)
        self.face = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        self.face.prepare(ctx_id=-1, det_size=(640, 640))

    def _smart_crop_box(self, img_rgb, face_frac: float = 0.20):
        """Face-anchored 3:4 torso box (l, t, w, h) or None. Fixes real-world photos
        (a full-body arms-out shot went 0.24 -> 0.94 identity with this)."""
        import cv2
        import numpy as np
        bgr = cv2.cvtColor(np.array(img_rgb), cv2.COLOR_RGB2BGR)
        faces = self.face.get(bgr)
        if not faces:
            return None
        f = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        x0, y0, x1, y1 = f.bbox
        fh = y1 - y0
        cx = (x0 + x1) / 2.0
        Hc = fh / face_frac
        Wc = 0.75 * Hc
        top = y0 - 0.15 * Hc
        left = cx - Wc / 2.0
        ih, iw = bgr.shape[:2]
        Wc = min(Wc, iw); Hc = min(Hc, ih)
        left = 0 if Wc >= iw else max(0.0, min(left, iw - Wc))
        top = 0 if Hc >= ih else max(0.0, min(top, ih - Hc))
        return int(left), int(top), int(Wc), int(Hc)

    @modal.method()
    def tryon(self, person_bytes: bytes, garment_bytes: bytes, cloth_type: str = "upper",
              steps: int = 40, guidance: float = 2.5, seed: int = 42,
              auto_crop: bool = True, composite: bool = True) -> bytes:
        """Render person wearing garment; return PNG bytes. cloth_type: upper|lower|overall.
        auto_crop face-anchors a torso crop (real-world photos); composite pastes ONLY the
        garment-mask pixels back into the full original, so face/hands/background stay real."""
        from PIL import Image
        orig = Image.open(io.BytesIO(person_bytes)).convert("RGB")
        box = self._smart_crop_box(orig) if auto_crop else None
        src = orig.crop((box[0], box[1], box[0] + box[2], box[1] + box[3])) if box else orig
        person = self._crop(src, (self.W, self.H))
        cloth = self._pad(Image.open(io.BytesIO(garment_bytes)).convert("RGB"), (self.W, self.H))
        mask = self.masker(person, cloth_type)["mask"]
        mask = self.mask_proc.blur(mask, blur_factor=9)
        gen = self._torch.Generator(device="cuda").manual_seed(seed) if seed != -1 else None
        result = self.pipe(
            image=person, condition_image=cloth, mask=mask,
            num_inference_steps=steps, guidance_scale=guidance, generator=gen,
        )[0]

        if composite and box:
            l, t, wc, hc = box
            import numpy as np
            m = (mask.convert("L") if hasattr(mask, "convert")
                 else Image.fromarray(np.asarray(mask)).convert("L")).resize((wc, hc))
            base = orig.crop((l, t, l + wc, t + hc)).convert("RGB")
            comp = Image.composite(result.resize((wc, hc)), base, m)
            out_img = orig.copy()
            out_img.paste(comp, (l, t))
        else:
            out_img = result

        buf = io.BytesIO()
        out_img.save(buf, format="PNG")
        return buf.getvalue()


@app.function(image=image, secrets=[modal.Secret.from_name("krey-render")])
@modal.asgi_app()
def web():
    """Authed HTTP front door: Service A POSTs person+garment, gets a PNG back.
    The canRender eligibility + token hold live on Service A (see render/README.md); this
    endpoint only checks a shared secret so nothing but Service A can spend GPU here."""
    from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
    from fastapi.responses import Response

    api = FastAPI()
    secret = os.environ["KREY_RENDER_SECRET"]

    @api.get("/healthz")
    def healthz():
        return {"ok": True}

    @api.post("/render")
    async def render_ep(
        person: UploadFile = File(...),
        garment: UploadFile = File(...),
        cloth_type: str = Form("upper"),
        x_krey_secret: str | None = Header(default=None),
    ):
        if not x_krey_secret or x_krey_secret != secret:
            raise HTTPException(status_code=401, detail="bad or missing render secret")
        if cloth_type not in {"upper", "lower", "overall"}:
            raise HTTPException(status_code=400, detail="cloth_type must be upper|lower|overall")
        png = Renderer().tryon.remote(await person.read(), await garment.read(), cloth_type)
        return Response(content=png, media_type="image/png")

    return api
