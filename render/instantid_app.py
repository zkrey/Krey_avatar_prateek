"""
Krey "Vibe" render (Service B, variant) — SDXL + InstantID as a Modal serverless-GPU endpoint.

The aspirational / trend-style render: generates a WHOLE coherent image with the user's identity
(InstantID keeps the face from one selfie) + an outfit/scene described by a prompt. Unlike CatVTON
(which warps/inpaints the exact garment and can distort), this generates a clean image — no melted
collars / stretched necks — at the cost of exact-garment fidelity ("gets the gist"). Same
fire-and-poll web contract + shared secret as render/modal_app.py, so Service A calls it the same way.

DEPLOY (Colab or any machine):
    pip install modal
    modal token new
    modal secret create krey-render KREY_RENDER_SECRET=<same secret as the CatVTON app>   # or reuse
    modal deploy instantid_app.py
Modal prints the web URL. On Service A (Railway) set:
    KREY_VIBE_RENDER_URL = <that URL>
    (KREY_RENDER_SECRET is already set and shared)

NOTES
-----
- Tracks the InstantID reference (github.com/InstantID/InstantID) — verify class/arg names against
  the repo if a deploy errors, same discipline as CatVTON. First cut; may need a tweak on deploy 1.
- GPU: SDXL + ControlNet + IP-Adapter needs headroom — defaults to L4 (24GB). T4 (16GB) may OOM.
  Override with KREY_VIBE_GPU. A payment method is required for L4/A10G.
- Weights (SDXL base + InstantID ControlNet/ip-adapter + antelopev2) are baked at build time.
- Licence: check the base SDXL model + InstantID licences before commercial use.
"""
import io
import os
import sys
from typing import Optional

import modal

GPU = os.environ.get("KREY_VIBE_GPU", "L4")
REPO_DIR = "/opt/InstantID"
INSIGHTFACE_ROOT = "/opt/insightface"                 # antelopev2 lands under here /models/antelopev2
BASE_MODEL = os.environ.get("KREY_VIBE_BASE", "wangqixun/YamerMIX_v8")  # the InstantID demo base
INSTANTID_REPO = "InstantX/InstantID"


def _bake():
    """Download all weights at image BUILD time so runtime containers start without fetching."""
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=INSTANTID_REPO, allow_patterns=["ControlNetModel/*", "ip-adapter.bin"])
    snapshot_download(repo_id=BASE_MODEL)
    from insightface.app import FaceAnalysis   # antelopev2 = InstantID's face embedder
    FaceAnalysis(name="antelopev2", root=INSIGHTFACE_ROOT,
                 providers=["CPUExecutionProvider"]).prepare(ctx_id=-1, det_size=(640, 640))


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "libgl1", "libglib2.0-0", "libgomp1")
    .run_commands(f"git clone https://github.com/InstantID/InstantID.git {REPO_DIR}")
    .pip_install(
        "torch", "torchvision",
        "diffusers==0.25.1", "transformers==4.37.2", "accelerate==0.27.2",
        "huggingface_hub==0.20.3",
        "insightface==0.7.3", "onnxruntime",
        "opencv-python-headless", "numpy==1.26.4", "pillow", "einops",
    )
    .run_function(_bake)
)

web_image = modal.Image.debian_slim(python_version="3.11").pip_install("fastapi[standard]")

app = modal.App("krey-vibe")


@app.cls(gpu=GPU, image=image, timeout=600, scaledown_window=120)
class Vibe:
    @modal.enter()
    def load(self):
        sys.path.insert(0, REPO_DIR)
        import cv2
        import numpy as np
        import torch
        from diffusers.models import ControlNetModel
        from huggingface_hub import snapshot_download
        from insightface.app import FaceAnalysis
        from pipeline_stable_diffusion_xl_instantid import StableDiffusionXLInstantIDPipeline, draw_kps

        self.cv2, self.np, self.torch, self.draw_kps = cv2, np, torch, draw_kps
        self.face = FaceAnalysis(name="antelopev2", root=INSIGHTFACE_ROOT,
                                 providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        self.face.prepare(ctx_id=0, det_size=(640, 640))

        id_dir = snapshot_download(INSTANTID_REPO, allow_patterns=["ControlNetModel/*", "ip-adapter.bin"])
        controlnet = ControlNetModel.from_pretrained(
            os.path.join(id_dir, "ControlNetModel"), torch_dtype=torch.float16)
        base = snapshot_download(BASE_MODEL)
        self.pipe = StableDiffusionXLInstantIDPipeline.from_pretrained(
            base, controlnet=controlnet, torch_dtype=torch.float16)
        self.pipe.cuda()
        self.pipe.load_ip_adapter_instantid(os.path.join(id_dir, "ip-adapter.bin"))

    @modal.method()
    def generate(self, person_bytes: bytes, prompt: str, negative: str = "",
                 steps: int = 30, guidance: float = 5.0,
                 id_scale: float = 0.8, adapter_scale: float = 0.8) -> bytes:
        from PIL import Image
        img = Image.open(io.BytesIO(person_bytes)).convert("RGB")
        bgr = self.cv2.cvtColor(self.np.array(img), self.cv2.COLOR_RGB2BGR)
        faces = self.face.get(bgr)
        if not faces:
            raise RuntimeError("no face detected in the photo")
        f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
        face_emb = f["embedding"]
        face_kps = self.draw_kps(img, f["kps"])
        out = self.pipe(
            prompt=prompt, negative_prompt=negative or None,
            image_embeds=face_emb, image=face_kps,
            controlnet_conditioning_scale=float(id_scale), ip_adapter_scale=float(adapter_scale),
            num_inference_steps=int(steps), guidance_scale=float(guidance),
        ).images[0]
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()


@app.function(image=web_image, secrets=[modal.Secret.from_name("krey-render")])
@modal.asgi_app()
def web():
    """Fire-and-poll front door (same contract as the CatVTON app): POST /render spawns and returns
    a call_id; GET /result?call_id=… returns the PNG when ready, else 202."""
    import modal as _modal
    from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
    from fastapi.responses import JSONResponse, Response

    api = FastAPI()
    secret = os.environ["KREY_RENDER_SECRET"]

    def _auth(x):
        if not x or x != secret:
            raise HTTPException(status_code=401, detail="bad or missing render secret")

    @api.get("/healthz")
    def healthz():
        return {"ok": True}

    @api.post("/render")
    async def render_ep(
        person: UploadFile = File(...),
        prompt: str = Form(...),
        negative: str = Form(""),
        x_krey_secret: Optional[str] = Header(default=None),
    ):
        _auth(x_krey_secret)
        fc = Vibe().generate.spawn(await person.read(), prompt, negative)
        return {"call_id": fc.object_id}

    @api.get("/result")
    def result_ep(call_id: str, x_krey_secret: Optional[str] = Header(default=None)):
        _auth(x_krey_secret)
        fc = _modal.FunctionCall.from_id(call_id)
        try:
            png = fc.get(timeout=0)
        except TimeoutError:
            return JSONResponse({"status": "pending"}, status_code=202)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"render failed: {e}")
        return Response(content=png, media_type="image/png")

    return api
