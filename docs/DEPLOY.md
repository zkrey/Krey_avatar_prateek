# Deploying Service A (the twin engine)

This turns the repo into a live API at an `https://…` address. Service A is **CPU-only**
(no GPU), so hosting is cheap. Everything below is a one-time setup; after it, every push
to the branch can auto-deploy.

## What you get
A running API with these routes (see `app/main.py`):
- `GET /health`
- `POST /capture/session`, `POST /capture/instagram` — build a twin from photos
- `POST /body/measure` — measurements from full-body frames
- `POST /style/profile`, `POST /fit/recommend` — style + fit
- `GET /twins/{id}`, `DELETE /twins/{id}` — fetch / erase the stored twin

## Prerequisites (accounts you create — free tiers to start)
1. **GitHub** — already done (this repo).
2. **A host** — **Railway** (recommended for speed) or Render. Connects to GitHub and
   builds the `Dockerfile` automatically.
3. **Supabase** — Postgres + Auth + Storage. Create the project in the **Mumbai
   (ap-south-1)** region for Indian data residency (DPDP).

> Costs at MVP scale: roughly ₹3–8k/month total across host + DB. All have free tiers to
> validate first.

## Step 1 — Deploy the engine (Railway)
1. Railway → **New Project → Deploy from GitHub repo** → pick this repo/branch.
2. Railway detects the `Dockerfile` and builds it (installs deps, bakes in the MediaPipe
   models). No build config needed.
3. It injects `$PORT` automatically; the container already respects it.
4. When the build finishes you get a public URL. Test it:
   ```bash
   curl https://<your-app>.up.railway.app/health
   # {"status":"ok","service":"twin-extraction",...}
   ```
That's the engine live. (The first `/capture/*` call downloads the InsightFace model once,
~300 MB — a slow first request; uncomment the pre-warm line in the `Dockerfile` to avoid
it. Or move to AWS/GCP **Mumbai** when you want residency + scale.)

## Step 2 — Add the database (Supabase)
The store is currently **in-memory** — twins vanish on restart. To persist:
1. Supabase → **New Project** (Mumbai region). Copy the **connection string** and keys.
2. Set them as env vars on the host (see `.env.example`): `DATABASE_URL=…`.
3. **Code step (not yet built):** swap `MemoryTwinStore` for a Postgres-backed store
   behind the same interface in `app/store.py`. Ask and I'll build it — it's a small,
   drop-in change since the store is already an interface.

Supabase also gives you **Auth** (accounts + the DOB the eligibility gate needs) and
**Storage** (transient raw photos, garment images) — one service for three needs.

## Step 3 — Secrets & config
- Never commit secrets. Set them in the host's **Variables** panel (or Supabase Vault).
- `.env.example` lists every variable; copy to `.env` for local dev only (it's gitignored).

## Step 4 — Auto-deploy (optional)
`.github/workflows` can run the test suite on every push and trigger a redeploy. Ask and
I'll add a GitHub Actions workflow (tests + deploy hook).

## Local run (no Docker)
```bash
pip install -r requirements.txt
./scripts/fetch_models.sh
MODELS_DIR=models uvicorn app.main:app --reload
```

## Local run (Docker, mirrors production)
```bash
docker build -t krey-service-a .
docker run -p 8000:8000 krey-service-a
curl http://localhost:8000/health
```

## Honest status
- **Ready to deploy:** the engine, models, gating, derive-and-discard, all flows.
- **Next code step for production:** the Postgres store backend (Step 2) — small, drop-in.
- **Still separate:** the mobile/web client, and Service B (generative render, needs GPU
  via Replicate/fal.ai). See the stack recommendation.
- **Licence:** InsightFace `buffalo_l` is research/non-commercial — swap for a licensed
  model before commercial launch (`docs/scope_bakeins.md`).
