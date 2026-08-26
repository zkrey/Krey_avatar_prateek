# models/

Runtime model files for Service A live here. They are **not** committed to git —
they are large binaries and freely re-downloadable from Google (Apache-2.0, MediaPipe).

Fetch them once on any machine that runs the server:

```bash
./scripts/fetch_models.sh          # downloads into this folder
```

| File | Used by | Purpose |
|------|---------|---------|
| `pose_landmarker_heavy.task` | `/twin/extract-measurements` | body pose landmarks |
| `hair_segmenter.tflite` | `/twin/extract-face` | hair mask → hair colour + texture |
| `face_landmarker.task` | `/twin/extract-face` | iris landmarks → eye colour |

The default `MODELS_DIR` is this folder. Point it elsewhere with
`MODELS_DIR=/path uvicorn app.main:app`. When a model is absent, its slice simply
returns empty and the endpoint composes whatever else it can — no hard failure.
