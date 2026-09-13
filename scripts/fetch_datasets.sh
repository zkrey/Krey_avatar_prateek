#!/usr/bin/env bash
# Fetch the open datasets Krey uses for VALIDATION + CALIBRATION into ./data/<key>/.
# Raw images are git-ignored (data/.gitignore) — only the registry + derived reports are
# committed. Rationale + verdicts: docs/skin_data_plan.md · registry: data/sources.json.
#
# Run only the sources you need. Several need a CLI + auth token you set up once:
#   - Kaggle:      pip install kaggle ; put kaggle.json in ~/.kaggle/ (kaggle.com -> API token)
#   - HuggingFace: pip install huggingface_hub ; huggingface-cli login  (for the SCIN mirror)
#   - Google Drive: pip install gdown         (for IndicFairFace's Drive link)
#   - SCIN GCS:    install gsutil (Google Cloud SDK) — the bucket is public, no login
#
# Usage:  ./scripts/fetch_datasets.sh <key> [<key> ...]
#         keys: indicfairface dermacon_in scin fairface_onnx
set -euo pipefail
DEST="${DATA_DIR:-data}"
mkdir -p "$DEST"

want=("$@"); [ ${#want[@]} -eq 0 ] && want=(indicfairface dermacon_in scin fairface_onnx hair_type_kavyasree)
has(){ printf '%s\n' "${want[@]}" | grep -qx "$1"; }

if has indicfairface; then
  echo "== IndicFairFace (Indian faces · CC0/CC-BY · VALIDATE) =="
  git clone --depth 1 https://github.com/aarishshahmohsin/IndicFairFace "$DEST/indicfairface/repo" 2>/dev/null || echo "  (repo present)"
  echo "  Images: open $DEST/indicfairface/repo/README.md, copy the Google Drive link, then:"
  echo "    pip install gdown && gdown --folder '<DRIVE_LINK>' -O $DEST/indicfairface/images"
fi

if has dermacon_in; then
  echo "== DermaCon-IN (Indian dermatology · Monk+Fitzpatrick · CALIBRATE · confirm licence) =="
  echo "  kaggle datasets download -d hiro002/dermacon-in-dataset -p $DEST/dermacon_in --unzip"
  command -v kaggle >/dev/null && kaggle datasets download -d hiro002/dermacon-in-dataset -p "$DEST/dermacon_in" --unzip || echo "  (install+auth the kaggle CLI, then re-run)"
fi

if has scin; then
  echo "== SCIN (US dermatology · Monk+Fitzpatrick · CALIBRATE secondary · SCIN DUL) =="
  echo "  Option A (GCS, public):  gsutil -m cp -r gs://dx-scin-public-data/dataset $DEST/scin"
  command -v gsutil >/dev/null && gsutil -m cp -r gs://dx-scin-public-data/dataset "$DEST/scin" || echo "  (install gsutil, or use the google/scin HuggingFace mirror)"
fi

if has hair_type_kavyasree; then
  echo "== Hair Type (kavyasreeb) · TRAIN hair-texture · confirm licence · not Indian =="
  echo "  kaggle datasets download -d kavyasreeb/hair-type-dataset -p $DEST/hair_type_kavyasree --unzip"
  command -v kaggle >/dev/null && kaggle datasets download -d kavyasreeb/hair-type-dataset -p "$DEST/hair_type_kavyasree" --unzip || echo "  (install+auth the kaggle CLI, then re-run) — see docs/hair_texture_plan.md (remap kinky->coily, drop dreadlocks)"
fi

if has fairface_onnx; then
  echo "== fairface-onnx (attribute MODEL · MIT/CC-BY · optional tool) =="
  git clone --depth 1 https://github.com/yakhyo/fairface-onnx "$DEST/fairface_onnx/repo" 2>/dev/null || echo "  (repo present)"
fi

echo
echo "Done. Raw data stays in $DEST/<key>/ (git-ignored)."
echo "Next: python -m bench.skin_report --data $DEST/<key>/images --name <key>   # writes data/reports/<key>.{json,md}"
