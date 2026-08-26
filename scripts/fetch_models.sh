#!/usr/bin/env bash
# Fetch the MediaPipe Tasks models Service A needs at runtime (Apache-2.0, Google).
# They are NOT committed to git — large binaries bloat history and are freely
# re-downloadable. Run this once per machine that actually runs the server.
#
#   ./scripts/fetch_models.sh            # -> ./models
#   MODELS_DIR=/path/to/models ./scripts/fetch_models.sh
#
# Idempotent: existing, non-empty files are skipped.
set -euo pipefail

DEST="${MODELS_DIR:-models}"
mkdir -p "$DEST"

# name -> canonical public URL (float16/float32 as published by MediaPipe).
declare -A MODELS=(
  ["pose_landmarker_heavy.task"]="https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
  ["hair_segmenter.tflite"]="https://storage.googleapis.com/mediapipe-models/image_segmenter/hair_segmenter/float32/latest/hair_segmenter.tflite"
  ["face_landmarker.task"]="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
)

for name in "${!MODELS[@]}"; do
  out="$DEST/$name"
  if [[ -s "$out" ]]; then
    echo "✓ $name already present ($(du -h "$out" | cut -f1)) — skipping"
    continue
  fi
  echo "↓ downloading $name ..."
  curl -fSL --retry 4 --retry-delay 2 "${MODELS[$name]}" -o "$out"
  echo "✓ $name ($(du -h "$out" | cut -f1))"
done

echo
echo "All models in: $DEST"
echo "Run the server with:  MODELS_DIR=$DEST uvicorn app.main:app --reload"
