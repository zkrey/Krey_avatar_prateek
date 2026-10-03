# Krey — Deployed Stack

_Snapshot of what's built and running. Last updated 2026-10-02._

A generative virtual try-on + peer-ranking product: render "this garment on me",
collect friends' pairwise votes, and measure whether peer ranking builds the
confidence to wear it.

> **Render limits & the owned-model plan:** the three render engines below are the
> interim commodity layer. The capability ceilings they can't cross — and the spec
> for a from-scratch frontier model to replace them — are logged in
> [`MODEL_CHALLENGES.md`](./MODEL_CHALLENGES.md). A current (2026-10) deep dive on
> CatVTON + Nano Banana and a survey of the other frontier engines (FASHN, Kolors,
> FLUX, IDM-VTON, OOTDiffusion, research models) is in
> [`RENDER_ENGINE_EVAL.md`](./RENDER_ENGINE_EVAL.md).

## One-line view
HTML/JS → FastAPI on Railway → Supabase (DB + storage) → three render backends
(CatVTON & SDXL+InstantID on Modal GPUs, Gemini/Nano-Banana via API), with
MediaPipe + Monk skin-tone profiling and a stdlib ranking engine.

## Layers

### Frontend
- Plain **HTML/CSS/JS**, no framework; mobile-first, inline JS.
- Pages: `/closet` (main try-on + looks tray), `/rank` (vote), `/results`,
  `/look/{id}`, `/studio` (self-serve upload), `/admin` (token-gated KPIs).

### Service A — app / API
- **FastAPI** (Python), pure-stdlib clients (no heavy deps on the web service).
- Hosted on **Railway**, service **`krey-labs`** → `krey-labs-production.up.railway.app`.
  - `krey-service-a` = older frozen tester service, left untouched.
- Builds from GitHub branch `claude/krey-frontend-d7zax0` (Railpack builder).

### Data + storage
- **Supabase** Postgres via PostgREST. Tables: `garments`, `looks`, `rank_sets`,
  `rank_votes`, `referrals`, `confidence_marks`, `garment_events` (+ RLS policies).
- **Supabase Storage**: public `looks` bucket for rendered images.
- Keys: anon key on Railway (read + RLS-guarded insert); service-role key only in
  the Kaggle ingestion notebook (never committed/deployed).

### Render engines (3, selectable behind `/closet` "Render style")
| Engine | What it does | Where | Status |
|---|---|---|---|
| **CatVTON** (SD-1.5 inpaint + DensePose/SCHP) | faithful real garment on the real photo | self-hosted, **Modal** app `krey-render` (T4), fire-and-poll | **Default** |
| **SDXL + InstantID** | stylised "80s vibe", identity from selfie, garment via text | self-hosted, **Modal** app `krey-vibe` (L4), model-CPU-offload | Retired from UI — the 80s look now routes to Nano ("80s ✨" chip = `banana80s`); backend branch kept but unsurfaced |
| **Nano Banana / Gemini 2.5 Flash Image** | person + garment images composed in one pass (frontier quality) | Google **Gemini API** (closed, paid) | **Live** — billing enabled 2026-10, verified end-to-end |

- Render weights are baked into the Modal images at build time.
- Service A → render via stdlib clients: `render/client.py` (CatVTON + vibe,
  fire-and-poll), `render/banana.py` (Gemini, synchronous).

### Compute / infra
- **Modal** — serverless GPU, scale-to-zero — both self-hosted render apps.
- **Google AI Studio / Gemini API** — frontier render.
- **Colab** — deploy driver for the Modal apps only (not a runtime dependency).

### Profiling / CV (in Service A)
- **MediaPipe** — pose landmarker (coverage/renderable-type detection) + FaceMesh
  (skin sampling).
- **Monk Skin Tone** — deterministic CIELAB / ΔE2000 classifier
  (`app/skin_tone.py` + `app/monk.py`); measured tone is fed into the generative
  render prompts for exposed-skin consistency.

### Analytics & unit economics
- `/admin?token=…` — live dashboard: realtime active users, renders, reshares, platform
  breakdowns, referral first-timers, cycle count, Glicko-2 leaderboard, K-factor,
  confidence lift. See [`UNIT_ECONOMICS.md`](./UNIT_ECONOMICS.md) for per-activity costs,
  the 10k-MAU monthly projection, downtime/redundancy, and capex vs opex.

### Attribution (planned, for later)
- [`ATTRIBUTION.md`](./ATTRIBUTION.md) — creator-provenance + revenue-share design: credit the
  originator of a fit/idea and share brand revenue back through vetted backlinks. Not built; the
  substrate (`looks.owner_hint`, `referrals`, `garment_events`) is already accruing so credit can
  be back-dated when it's switched on post-validation.

### Ranking engine
- `app/rating.py` — pure stdlib: Glicko-2, Bradley-Terry (regularized Zermelo),
  Plackett-Luce (per-rank probabilities), Kendall's τ (self↔crowd convergence),
  plus a mixed epsilon-greedy adaptive pair sampler.

### Ingestion
- Kaggle/Colab notebook → Supabase: garment catalog (~383 items) with
  `cloth_type` (upper/lower/overall) + segment/subsegment taxonomy.

## Config (env vars on Railway `krey-labs`)
- `KREY_SUPABASE_URL`, `KREY_SUPABASE_KEY` (anon) — catalog + looks + votes.
- `KREY_MODAL_RENDER_URL`, `KREY_RENDER_SECRET` — CatVTON (shared secret).
- `KREY_VIBE_RENDER_URL` — SDXL+InstantID.
- `GEMINI_API_KEY` — Nano Banana (needs the Cloud project on paid/billing).
- `KREY_ADMIN_TOKEN` — `/admin` gate.

## Open threads
- **Nano Banana**: ✅ billing enabled (2026-10), verified end-to-end (API returns the
  composed image on the real person+garment+text path). Live behind the "Studio ✨" chip.
- **Ranking**: if votes read 0, ensure the `rank_votes` public-read RLS policy is
  applied in Supabase.
- **Security**: ✅ resolved (2026-10) — Gemini key rotated (old key verified dead/401,
  new `krey-labs-gemini` live/200) and the setup Modal CLI token revoked.
