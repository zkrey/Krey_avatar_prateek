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

# Bake the MediaPipe models into the image (~35 MB) so boot needs no network.
RUN bash scripts/fetch_models.sh

# OPTIONAL — pre-warm InsightFace (buffalo_l, ~300 MB) so the FIRST capture is fast and
# never depends on a runtime download. Uncomment for production reliability (bigger image):
# RUN python -c "from insightface.app import FaceAnalysis; \
#     a=FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); a.prepare(ctx_id=-1)"

EXPOSE 8000
# Hosts (Railway/Render) inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
