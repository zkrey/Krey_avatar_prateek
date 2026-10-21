# Krey — Decision & build log (continuity record)

_Last updated 2026-10-21. This is the **human-readable memory** of what Krey is, what we've
built and why, and what's deliberately parked — written so the knowledge survives even if a
chat transcript, a session, or an account is lost. No secrets live here (see `BACKUP.md` for
the continuity doctrine and why). When a decision changes, update this file; it is the
single place a new collaborator (or a future us) reads first._

> **Secrets rule:** this file never contains tokens, keys, admin passwords, or PATs. Those
> live only in Railway env and are rotated per `BACKUP.md`. If you ever need to reference one,
> name the *variable*, never the value.

---

## 1. What Krey is

A generative **virtual try-on + peer-styling** fashion web app. A user adds a selfie, tries
any garment / trend / their own wardrobe on themselves via an image model, and asks their
close circle which look is most *them*. The habit is **knowing how clothes fit and look on
you** — checked casually, without the old forced cost of buying to find out.

**The core loop:** add photo → try a look on yourself → ask your people → see what they
picked → do it again. Every feature either feeds this loop or removes friction from it.

**Monetization** is governed separately by `DOCTRINE.md` (the Habit Line: give away the
habit, charge for created value on top of it). **Positioning / GTM** is `POSITIONING.md`
(the consideration gradient). This doc is the *build decision log* under those.

## 2. Architecture (as built)

- **Service A** — FastAPI app (`app/main.py`), pure-stdlib clients (`urllib`, no heavy deps
  in the request path). Hosted on **Railway** (service `krey-labs` →
  `krey-labs-production.up.railway.app`), **Railpack** builder, deployed from branch
  `claude/krey-frontend-d7zax0`.
- **Data** — **Supabase** Postgres via **PostgREST**; a public `looks` Storage bucket for
  rendered images. The anon key is used **server-side only** — the browser never queries
  Supabase directly. RLS policies gate insert/select/update/delete. Schema lives in
  `docs/catalog_schema.sql`.
- **Render** — Nano Banana / Gemini image model (`render/banana.py`, env
  `KREY_BANANA_MODEL`, default `gemini-3.1-flash-image`); multi-`inlineData` parts for
  multi-garment composition. A `gemini-flash-latest` tagger labels garments.
- **Identity** — InsightFace / ArcFace (`buffalo_s`) face embeddings (`app/identity.py`);
  render identity = ArcFace cosine original-vs-render, floor `RECOGNISABLE_COSINE = 0.50`,
  target ~85% likeness (`bench/render_eval.py`).
- **Fit/size** — `app/fit_score.py` (`rule-fit-v0`): body girths × garment size chart →
  `fits / snug / size_up / size_down`. Config in `config/size_charts.json` + `config/fit.json`.
- **Ranking** — Glicko-2 / Bradley-Terry (`app/rating.py`); the admin view shows W/G
  (wins/games).
- **Front end** — server-rendered HTML pages: `app/closet.html` (home + try-on),
  `app/wardrobe.html` (own-wardrobe), `app/rank.html` (the ask-your-people page),
  `app/myfits.html` (`/me` hub).

**Deploy pattern:** commit → `git push -u origin claude/krey-frontend-d7zax0` →
re-pin the Railway service source to the repo+branch → wait ~8 min (Railpack builds are
slow) → confirm `latestDeployment.status == SUCCESS`. Full detail in `DEPLOY.md`.

**Sandbox reality (for whoever runs sessions):** the build sandbox cannot reach the Railway
domain, `status.railway.com`, or `drive.google.com` (proxy DNS blocked); it *can* reach
`googleapis` + GitHub. numpy/fastapi are not installed locally, so `main.py` can't run in the
sandbox — stdlib modules (e.g. `fit_score`) can be tested directly; JS is checked with
`node --check` on extracted `<script>` blocks.

## 3. Feature decision log (what we built and why)

Chronological-ish. Each entry = the problem, the decision, and where it lives.

1. **Stylist composer ("✨ Make me a fit")** — read saved wardrobe → LLM stylist composes an
   outfit → multi-garment render on the user → feeds the share loop.
   `render/banana.py:compose_fit`, `generate_outfit`.
2. **Wardrobe dead-end fix** — an uploaded garment had no render path. Added per-garment
   "See it on me" + stylist entry so a custom upload re-enters the cyclic loop.
3. **Prominent closet → wardrobe entry** + an **expiry/outdate audit** (fixed a deprecated
   model fallback → bumped `KREY_BANANA_MODEL` default to `gemini-3.1-flash-image`).
4. **Render → share lift ("learning module")** — decision was **both measure + nudge**:
   funnel analytics (rendered/multi/ballot/share rates in `/admin`) + render-done nudges,
   then a **guided coach** that hand-holds render → share on both closet and wardrobe.
5. **Language doctrine audit** — rewired end-user copy to positive framing (see §5).
6. **Face-distortion investigation → identity gate** — ArcFace gate on every render,
   "is this you?" feedback, a **self-tuning floor** (`catalog.learned_id_floor`, env
   `KREY_ID_MIN_COSINE` / `KREY_ID_AUTOTUNE`), passive per-render scoring, and
   `/admin` render_quality + funnel. Auto-retry once if a render is below the floor.
   `app/main.py:_render_with_identity_guard`, `_cos_to_ref`, `_biggest_face_embedding`.
7. **Results access** — owners couldn't find their standings. Built the **`/me` "Your fits"
   hub** (`app/myfits.html`) with live standings + a **15-day prune** of old entries, a
   prominent "see what your people picked" button on both pages, and a results tab on the
   rank page (owner anytime; voters only *after* they submit).
8. **"Krey remembers you" profile** — consented per-user face embedding + Monk skin tone +
   body measurements; upholds the user's *true* tone from earlier good selfies; **delete
   anytime** (`/me/face/delete`). Schema: `face_profiles` in `catalog_schema.sql`. One-tap
   consent, never a form (lazy doctrine).
9. **Lighting fix** — dark selfies rendered a darker face than reality. Added a
   **conservative, faithful** auto-correct (`_normalize_lighting`: gentle gamma lift clamped
   [0.70, 1.0], applied only when the image is genuinely dark (meanL < 110), plus
   half-strength gray-world white balance). Explicitly must **not distort the user's actual
   pic** — a well-lit selfie is left untouched. Tone profile upholds true tone over a poor
   current reading.
10. **Backdrop picker** — choose a background (incl. **"Surprise me"** = model picks one that
    suits the garment) + a one-time tutorial tip. `_BACKGROUNDS` / `_bg_clause`.
11. **Pose picker** — `_POSES` / `_pose_clause`; default "natural" = no change, "surprise" =
    model picks.
12. **Size recommendation ("What's my size?")** — reuses the existing `fit_score` engine.
    **Quick height + weight** (one-time, then instant), garment-aware charts, and a
    **brand-exact hook** (uses a provided chart when available). `/fit/recommend`,
    `/fit/quick`, `_estimate_body_cm`. Added `mens_bottom_regular`, `womens_dress_regular`,
    `unisex_kurta_regular` to `size_charts.json` (kurta keyed on chest only so its loose cut
    doesn't trigger a false "size down").
13. **Home screen redesign** — "See how good you look" read as derogatory/confusing. Redone
    into two equal cards: **"✨ Try on a look"** and **"👗 Build your wardrobe."** Tapping
    try-on reveals the photo gate. `app/closet.html`.
14. **Social-connect plan** — `SOCIAL_CONNECT.md`: OAuth "connect & import *your own* data"
    only; friend graphs stay closed; DPDP/GDPR/app-review gated. Planning, not built.
15. **Positioning thesis** — `POSITIONING.md`: consideration gradient; adaptive buy CTA;
    B2B "mirror tech" parked for later.

## 4. Current live state

- Branch `claude/krey-frontend-d7zax0`, last known good deploy of the home redesign (Railway
  `latestDeployment.status == SUCCESS`). The positioning + continuity docs are docs-only
  (no deploy needed).
- Early identity feedback (very small n) hinted the floor may want to rise above the 0.50
  default, but n was too small to move it — left to the self-tuner.
- **Railway connector** has dropped its session; re-authorize in claude.ai connector settings
  before the next deploy.

## 5. Standing invariants (doctrine we hold to)

These are **hard rules**, not preferences. Breaking one is a regression.

- **Language doctrine (end-user copy):** never use *validate / rank / rate / vote / judge /
  winner / ballot* in anything a user reads. Keep those as **internal** code/table names
  only. User-facing framing is warm and positive ("ask your people", "what's most you").
- **Lazy doctrine:** never make the user think or fill a form when a tap will do. Ask for
  data (height/weight, consent) **once**, then it's instant. Consent is one tap, not a form.
- **No fabricated brand data:** never invent a brand's size chart or spec that could mislead
  a purchase. Build a *hook* for real brand data instead (we refused to fake a FabIndia chart).
- **Biometric consent:** face / tone / measurements require explicit one-tap consent and
  **delete-anytime** (`/me/face/delete`). Used only to make the user's *own* looks better.
- **Faithful rendering:** corrections (lighting, tone) must not distort the user's real
  appearance. Conservative by default; a good input is left alone.
- **Monetization:** the Habit Line in `DOCTRINE.md` — the fit answer and the habit are never
  moved behind the paywall.
- **Secrets:** no token/key/PAT value ever enters the repo, a commit message, a PR, code
  comments, or any pushed artifact. Env only. (See `BACKUP.md`.)

## 6. Parked (captured, not acted on)

- **B2B "mirror tech"** — in-store Krey mirror closing the tactile-check loop for festive;
  revisit when that discussion opens (`POSITIONING.md` §parked).
- **Social connect** — growth/onboarding accelerator; ship only behind OAuth + privacy
  policy + app review (`SOCIAL_CONNECT.md`).
- **Creator commerce / attribution payout** — gated on a product/affiliate source + the
  attribution ledger (`WARDROBE.md` M4, `ATTRIBUTION.md`).
- **Identity floor tuning** — revisit once render-quality data has volume.

---

_Index of the knowledge base: `DOCTRINE.md` (monetization), `POSITIONING.md` (GTM),
`WARDROBE.md` (create→broadcast→earn), `ATTRIBUTION.md` (credit+payout), `SOCIAL_FLOW.md`
(the loop), `SOCIAL_CONNECT.md` (data import plan), `CATALOG_INGEST.md` (seller inventory +
textures), `UNIT_ECONOMICS.md` (render costs), `DEPLOY.md` + `BRANCHING_SOP.md` (ops),
`BACKUP.md` (continuity), `catalog_schema.sql` (data model)._
