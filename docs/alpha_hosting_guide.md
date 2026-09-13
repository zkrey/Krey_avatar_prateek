# Alpha hosting guide — for Sohan

How to put the Krey alpha (`/alpha` Twin Check) online, how it connects to the Krey
algorithm, how to verify it works, and how alpha-user feedback comes back for rework.
This is **Step 1** of `docs/alpha_render_rollout.md` (GPU-free). Step 2 (your local-GPU
render benchmark) comes only after alpha feedback is positive.

---

## 0. What you're deploying (one thing)

A single FastAPI service (`app/main.py`). It serves **both** the web pages **and** the
algorithm, on the **same origin** — so there's nothing to "connect": the `/alpha` page
calls the extraction endpoints on the same server.

- **`/alpha`** — alpha-user Twin Check (add ≤5 photos → twin read → flag what's wrong)
- **`/tester`** — internal team QA console (all endpoints)
- **`/health`** — liveness probe
- Algorithm endpoints the pages call: `/capture/session` (owner-pick + appearance +
  recognition), `/body/measure` (measurements), `/feedback` (flags), plus the single-photo
  `/twin/extract-*` routes.

GPU-free: the pipeline stops before any render (Service B). No GPU needed for alpha.

---

## 1. Where to host

**Recommended: Railway** (the repo already has a `Dockerfile` tuned for it; `docs/DEPLOY.md`
has the fuller version). Any Docker host works (Render, Fly.io, a plain VM) — the only
requirements are Docker + enough RAM.

- **Region:** Mumbai / closest to users (India-first).
- **RAM: ≥ 2 GB** (buffalo_l face model + MediaPipe pose + onnxruntime on CPU). 2–4 GB is
  comfortable; 512 MB **will OOM** on the first capture.
- **CPU:** shared is fine for alpha; the render (the slow, GPU part) isn't in this service.
- **Disk:** ephemeral is fine — nothing is persisted (see §5, §6).

---

## 2. Deploy it — step by step (Railway)

1. **Railway → New Project → Deploy from GitHub repo** → pick `zkrey/Krey_avatar_prateek`.
2. **Settings → Source → Branch = `main`.** (Not `main`'s old state — `main` is now the
   single source of truth; deploy it.)
3. Railway detects the **`Dockerfile`** and builds it. The build bakes everything in:
   - MediaPipe models (pose / hair / face) via `scripts/fetch_models.sh`,
   - InsightFace **buffalo_l** pre-warmed (so the first `/capture/session` is fast and
     doesn't download at runtime). Build takes a while (downloads ~300 MB) — normal.
4. **Settings → Resources → set memory to ≥ 2 GB.**
5. **Port:** none to set — the container reads Railway's `$PORT` automatically
   (`uvicorn ... --port ${PORT:-8000}`).
6. **Env vars:** none required for alpha. `MODELS_DIR` is baked to `/app/models`. Optional:
   `KREY_TOKEN_*` / `KREY_EARN_*` to tune the sample economy; leave defaults for alpha.
7. **Deploy.** Railway gives you a public URL, e.g. `https://krey-alpha.up.railway.app`.

**If the build fails,** copy the Railway build log to the team (Prateek/Claude) — the usual
culprits are memory during buffalo_l warm or a model URL hiccup; both are quick fixes.

---

## 3. Verify it works (5 minutes)

Against your deploy URL `$U`:

1. **`GET $U/health`** → `{"status":"ok",...}`. Service is up.
2. **Open `$U/tester`** (team console) → run the **Twin** tab with a real face photo and a
   full-body photo. You should see Monk tone, hair, eye, and (with the pose model) body
   measurements. This proves the algorithm is live.
3. **Open `$U/alpha`** (what alpha users get) → tick 18+, add up to 5 photos, **Read my
   twin**. You should see: "found you in N of M", skin/hair/eye/shape/proportions with
   confidence, measurements when height is entered, and the flag / confirm controls.
4. **Watch the logs** (Railway → Deployments → Logs). Each action prints a structured JSON
   line (`twin_extracted`, `eligibility`, `feedback`, …). That log stream is also how you
   read feedback (§5).

Notes:
- First `/capture/session` is quick (buffalo_l pre-warmed). First `/body/measure` loads the
  pose model once, then is fast.
- If `/body/measure` returns **503**, the pose model isn't present — it should be baked by
  the Dockerfile; re-check the build ran `fetch_models.sh`.

---

## 4. How `/alpha` connects to the Krey algorithm

Nothing to wire — it's same-origin. When an alpha user taps **Read my twin**, the page:

1. `POST /capture/session` with the ≤5 photos + a consenting-adult gate → the algorithm
   finds the owner (ArcFace/buffalo_l), fuses appearance, returns identity confidence +
   skin/hair/eye and the decision (accept / reconfirm / retake).
2. `POST /body/measure` (only if height was given) → pose-based measurements + body shape,
   scaled to the declared height.
3. Everything is shown with per-field confidence; low-confidence fields ask a one-tap
   confirm; a soft "looks off — retake?" hint appears on a low match. **No render is run** —
   zero GPU cost.

Photos are **derive-and-discard**: processed in a temp dir, deleted right after; only the
compact derived record can be kept, and only if a `user_id` is supplied (alpha uses guest by
default, so nothing is stored).

---

## 5. How you get alpha feedback (for rework)

When an alpha user flags a wrong value and hits **Send feedback**, the page does
`POST /feedback` with a `note` that lists **each flagged field, what it showed, what the user
says it should be, what they confirmed, and a snapshot of the full read** (plus name/email if
they gave them).

The server does two things with it:
- emits a compact `feedback` analytics event (severity / route / kind / dedup), **and**
- emits a **`feedback_ticket`** line carrying the **full ticket incl. the note** — this is
  the rework detail.

Both go through the **same pluggable sink**. Out of the box the sink **prints JSON lines to
stdout**, i.e. into your **Railway logs**. So for alpha:

**Read feedback now:** Railway → Logs, filter for `feedback_ticket`. Each line is a complete
flag report you can action. Example (abbreviated):
```json
{"event":"feedback_ticket","ticket":{"severity":"normal","route":"standard","kind":"...",
 "note":"ALPHA TWIN CHECK — flagged as wrong:\n• Eye colour: shown \"Brown\" → should be: green\n..."}}
```
`grep feedback_ticket` (or Railway's log search) gives you every one.

**Make it durable (recommended once flags start coming):** logs roll off. Pick one, low
effort → higher:
- **Log drain** — Railway can forward logs to a destination you keep (a bucket, Logtail,
  etc.). Zero code.
- **Swap the sink** — `app/main.py` builds `Analytics()` with the default `stdout_sink`.
  Point it at a function that writes each event to **Supabase** (a `feedback` table) or posts
  `feedback_ticket` events to a **Slack webhook**. ~20 lines, no other change — every event
  (incl. tickets) flows there automatically.
- **Full loop** — `docs/FEEDBACK_LOOP.md` describes routing a ticket to a sandbox / GitHub
  issue for the live→fix→deploy cycle; wire that when alpha graduates.

The ticket also flags **device-specific visual bugs** (`route: "device_farm"`) vs general
issues (`route: "standard"`), so you can triage rendering/UX bugs separately from algorithm
misreads.

---

## 6. Privacy / data notes (say this to alpha testers)

- No account needed (guest); the page asks only for a **18+ consent** tick.
- Photos are **processed then discarded** — nothing raw is stored. Only the derived twin can
  be kept, and only with a `user_id`; alpha runs as guest, so it isn't.
- The in-memory twin store (`MemoryTwinStore`) and default log sink are **ephemeral** — fine
  for alpha; swap for a DB before anything real.
- InsightFace `buffalo_l` is **research/non-commercial** — fine to prove alpha; swap for a
  licence-cleared model before commercial launch (`docs/scope_bakeins.md`).

---

## 7. Then Step 2 — your local GPU (after positive feedback)

Once the twin read tests well (low flag rate, ~85% likeness, skin ΔE small), stand up the
generative render on your GPU to measure **render speed + accuracy → cost/render**, before
any cloud GPU. Everything for that is in **`docs/alpha_render_rollout.md`** (which points to
`docs/local_render_setup.md` for the CatVTON/detectron2 setup and `bench/gpu_benchmark.py`'s
`local` provider for logging GPU-seconds). Don't start Step 2 until Step 1 feedback is good.
