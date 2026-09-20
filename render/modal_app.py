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

GPU = os.environ.get("KREY_RENDER_GPU", "L4")      # "T4" | "L4" | "A10G" | "A100"
CATVTON_DIR = "/opt/CatVTON"
CATVTON_REPO = "zhengchong/CatVTON"
BASE_REPO = "runwayml/stable-diffusion-inpainting"


def _bake_weights():
    """Runs at image BUILD time so runtime containers never download the ~5 GB of weights."""
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=CATVTON_REPO)        # checkpoint + DensePose + SCHP
    snapshot_download(repo_id=BASE_REPO)           # SD-inpainting base


# Image mirrors the benchmark install exactly: keep Modal's torch/CUDA, strip CatVTON's torch
# pin, add PyAV + detectron2 (the DensePose backbone), then bake the weights.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "libgl1", "libglib2.0-0", "libgomp1")
    .run_commands(
        f"git clone https://github.com/Zheng-Chong/CatVTON.git {CATVTON_DIR}",
        f"grep -viE '^(torch|torchvision|torchaudio)' {CATVTON_DIR}/requirements.txt > /tmp/req.txt",
        "pip install -r /tmp/req.txt",
        "pip install av 'git+https://github.com/facebookresearch/detectron2.git'",
    )
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
        )
        self.mask_proc = VaeImageProcessor(
            vae_scale_factor=8, do_normalize=False, do_binarize=True, do_convert_grayscale=True
        )
        self.masker = AutoMasker(
            densepose_ckpt=os.path.join(repo, "DensePose"),
            schp_ckpt=os.path.join(repo, "SCHP"),
            device="cuda",
        )

    @modal.method()
    def tryon(self, person_bytes: bytes, garment_bytes: bytes, cloth_type: str = "upper",
              steps: int = 40, guidance: float = 2.5, seed: int = 42) -> bytes:
        """Render person wearing garment; return PNG bytes. cloth_type: upper|lower|overall."""
        from PIL import Image
        person = self._crop(Image.open(io.BytesIO(person_bytes)).convert("RGB"), (self.W, self.H))
        cloth = self._pad(Image.open(io.BytesIO(garment_bytes)).convert("RGB"), (self.W, self.H))
        mask = self.masker(person, cloth_type)["mask"]
        mask = self.mask_proc.blur(mask, blur_factor=9)
        gen = self._torch.Generator(device="cuda").manual_seed(seed) if seed != -1 else None
        result = self.pipe(
            image=person, condition_image=cloth, mask=mask,
            num_inference_steps=steps, guidance_scale=guidance, generator=gen,
        )[0]
        buf = io.BytesIO()
        result.save(buf, format="PNG")
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
