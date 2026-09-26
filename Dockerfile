# Krey — Service A (twin-extraction engine). CPU-only FastAPI service.
# Builds a self-contained container that any host (Railway, Render, Fly, AWS Mumbai…)
# can run. MediaPipe models are baked in at build; InsightFace (buffalo_l) downloads on
# first request unless you pre-warm it (see the commented step below).
FROM python:3.11-slim

# System libraries: build tools for InsightFace's C extension; libEGL/libGL/glib for
# MediaPipe + OpenCV; curl for the model fetch.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl libegl1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODELS_DIR=/app/models \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Python deps first so this layer caches across code changes.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App code + the model fetch script.
COPY app ./app
COPY scripts ./scripts
COPY models ./models
# render.client (pure stdlib) is imported by Service A for the try-on render flag/call.
# render.modal_app is NOT imported at runtime (it needs `modal`), only used for `modal deploy`.
COPY render ./render

# Bake the MediaPipe models into the image (~35 MB) so boot needs no network.
RUN bash scripts/fetch_models.sh

# Pre-warm the InsightFace model pack at build so the first /capture/session needs no
# runtime download (hosts with an ephemeral filesystem, e.g. Railway/Render, would otherwise
# re-fetch on every restart). Downloads into /root/.insightface, the path the app reads at
# runtime. Default is buffalo_s (a ~15 MB MobileFaceNet recogniser) so the resident footprint
# fits a 1 GB host — buffalo_l (ResNet50 ArcFace) OOM-kills a 1 GB container at model load.
# Must match the runtime KREY_FACE_MODEL; on a larger host build with
# --build-arg KREY_FACE_MODEL=buffalo_l and set the same env for best accuracy.
ARG KREY_FACE_MODEL=buffalo_s
ENV KREY_FACE_MODEL=${KREY_FACE_MODEL}
RUN python -c "import os; from insightface.app import FaceAnalysis; \
    a=FaceAnalysis(name=os.environ['KREY_FACE_MODEL'], providers=['CPUExecutionProvider']); a.prepare(ctx_id=-1)"

EXPOSE 8000
# Hosts (Railway/Render) inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
