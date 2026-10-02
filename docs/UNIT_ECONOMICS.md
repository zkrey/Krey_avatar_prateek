# Krey — Analytics, Unit Economics & Capacity Plan

_How we measure the social test, what each action costs, and what the monthly bill looks
like at 10k users. Pricing verified 2026-10-02; all projections state their assumptions._

> **Urgent infra note (2026-10):** `gemini-2.5-flash-image` is **deprecated and scheduled
> for shutdown on 2026-10-02**. The default render model was migrated to
> **`gemini-3.1-flash-image`** via the `KREY_BANANA_MODEL` env var (no code change). Keep an
> eye on Google's deprecation notices — the model id is a one-line env flip.

---

## 1. Analytics — what we track and where to read it

All of it lands on **`/admin?token=…`** (one page, live). Backed by `garment_events`
(view/try/share with `session_hint`, `channel`, `created_at`) and `referrals`
(`visitor_hint`, `source`, `activated`). No new infra — just reads.

| What you asked for | Metric on /admin | How it's derived |
|---|---|---|
| How many people are using (realtime) | **Active now** (last 15 min) + **Active today** | distinct `session_hint` in `garment_events` within the window |
| Total reach | **Total users** | distinct `session_hint` ever |
| How many photos are they rendering | **Renders** | count of `try` events (every render logs one) |
| How many reshares | **Reshares** | count of `share` events (ballot, single look, results) |
| Which platform drives ranking | **Ranking clicks by platform** + **Referrals by platform** | inbound `document.referrer` on `/rank` → logged as `channel` (whatsapp/instagram/…); referral `source` tagged `rank/<platform>` |
| Referral first-timers | **Referral first-timers** | distinct `visitor_hint` in `referrals` |
| Cycle count per user | **Total cycles** + **Cycles / owner** | see definition below |
| Share channel (outbound) | **Shares by channel** | `channel` on share events (native / whatsapp) |

**Cycle definition.** A *cycle* = one completed **rank → referral → new user** loop. We
approximate **total cycles = activations** (each activated referral is one new person who
entered the loop and can now start their own rank), and **cycles/owner = activations ÷
distinct ballot owners**. So "rank → referral → rank → referral" by one chain reads as 2
cycles. This is a proxy; a precise chain-depth metric is a later refinement.

**Platform-attribution caveat (honest).** The Web Share API does **not** reveal which app
the user picked — a native share logs as `native`, only the WhatsApp fallback logs as
`whatsapp`. So the reliable "which platform" signal is the **inbound** side: where the
`/rank` click came from (`document.referrer`). That's the number to trust for "which
platform drives ranking."

---

## 2. Cost inputs (verified 2026-10-02)

| Resource | Price | Source |
|---|---|---|
| **Nano Banana — Gemini 3.1 Flash Image** (1K image) | **~$0.067 / image** (output) + ~$0.001 input | [pricing](https://www.aifreeapi.com/en/posts/gemini-flash-image-generation-pricing), [Google](https://ai.google.dev/gemini-api/docs/pricing) |
| — Gemini 3.1 Flash **Lite** Image (1K) | ~$0.034 / image, ~2.7× faster | same |
| — Batch mode (async) | ~50% off → ~$0.034 / image | same |
| **CatVTON** (self-hosted, Modal **T4**) | ~$0.59 / GPU-hr → **~$0.01–0.03 / render** (40–170 s) | Modal pricing; scale-to-zero when idle |
| **Railway** (Service A, Hobby) | $5/mo base + usage; ~$10–40/mo at this scale | Railway usage-based |
| **Supabase** Pro | $25/mo (8 GB DB, 100 GB storage, 250 GB egress incl.) | storage $0.021/GB, egress $0.09/GB over |

**Render output size matters.** Nano returns ~1.5 MB PNGs. At scale, storage + egress is
driven by this. Re-encoding looks to **JPEG (~200 KB)** before upload cuts storage/egress
~7× — the single biggest cost lever after the per-image fee. (Flagged as a quick win.)

---

## 3. Unit economics (per activity)

| Activity | Marginal cost | Notes |
|---|---|---|
| **Render — Nano (default)** | **~$0.07** | the dominant cost; ~$0.034 on Lite/batch |
| **Render — CatVTON (fallback)** | **~$0.02** | compute only, no vendor per-image fee, private |
| Photo analyze (coverage) | ~$0.0001 | CPU on Railway, MediaPipe, no GPU |
| Vote | <$0.00001 | one Supabase row insert |
| Share / event log | <$0.00001 | one row insert |
| Ballot/results view by a friend | ~$0.002 (PNG) / ~$0.0003 (JPEG) | image egress, 3 looks |

**Per render session** (assume 3 renders, mostly Nano, 1 ballot shared, seen by ~6 voters):
≈ 3 × $0.07 + 6 × $0.002 ≈ **~$0.22 / active session**. On CatVTON-default or JPEG that
drops to **~$0.07–0.10**.

**Session time** (observed/engineered): Nano render **~15–30 s** (synchronous); CatVTON
**~40 s warm, up to ~170 s cold** (T4 scale-to-zero). Analyze is sub-second. So a 3-render
Nano session is **~1–2 min of active time**; a CatVTON cold session can hit 5 min.

---

## 4. Monthly projection — 10k MAU

**Assumptions:** 10,000 monthly active users · 4 renders/user avg · engine mix 80% Nano /
20% CatVTON · 1.5 ballots/user shared · ~6 voters/ballot · 3 looks viewed each · PNG today.

| Line | Volume | Cost |
|---|---|---|
| Nano renders | 40k × 80% = 32k × $0.067 | **~$2,150** |
| CatVTON renders | 40k × 20% = 8k × $0.02 | ~$160 |
| Supabase Pro base | — | $25 |
| Egress (PNG) | ~400 GB − 250 incl. → 150 GB × $0.09 | ~$14 |
| Railway | — | ~$30 |
| **Total opex** | | **≈ $2,380 / month** |

- **Blended cost / render ≈ $0.058** · **cost / MAU ≈ $0.24.**
- **Nano is ~90% of the bill** — it is the thing to optimize.
- **With JPEG + Lite + CatVTON-default-for-clean-shots:** the same 10k MAU drops to **~$900–
  1,200/mo** (cost/MAU ~$0.10). Those three levers are the roadmap.

**Scale-up (linear in renders):** 100k MAU ≈ **$24k/mo** at today's mix, or **~$9–12k** with
the levers. Cost is almost entirely **marginal per render** — there is no step-function until
you decide to self-host the frontier model.

---

## 5. Capex vs opex

- **Hard capex today: ≈ $0.** Everything is serverless/usage-based (Gemini API, Modal
  scale-to-zero, Railway, Supabase). No reserved hardware, no upfront commit.
- **What to budget as "capex-like":** (a) a **monthly opex float** — set it at **~$3.5–4k/mo
  at 10k MAU** (the ~$2.4k projection + headroom for retries, spikes, and voters-per-ballot
  running hot); (b) **prepaid API credits** if Google/Modal offer committed-use discounts at
  volume; (c) the real future capex — **an owned render model + GPU fleet** (see
  `MODEL_CHALLENGES.md`), which only pencils out above roughly **$10–20k/mo of Nano spend**,
  i.e. ~150–300k renders/month. Below that, renting is cheaper than owning.

---

## 6. Downtime & redundancy (and what it costs)

The product already has **two independent render engines**, which is the core resilience play:

| Failure | Blast radius | Mitigation (today / planned) |
|---|---|---|
| **Nano / Google outage** | Studio + Trends down | *planned:* auto-fallback to CatVTON for garment try-ons; Trends degrade to "try again." Keep both funded. |
| **Modal / CatVTON down** | Realistic-fit + cold renders | Nano covers garment try-ons; CatVTON is the fallback, not the primary. |
| **Railway down** | whole app down (SPOF) | healthcheck + `/health/cycle`; consider a 2nd replica / region (Railway multi-region) for ~2× Service-A cost (~$30–60/mo — cheap insurance). |
| **Supabase down** | DB/storage/votes down (SPOF) | app already degrades gracefully (sample catalog on read error); writes are best-effort, never 500 the UI. A read replica is the next step. |

**Availability math (rough):** render path with two engines ≈ **99.99%+** (either can serve);
the real single points of failure are **Railway** and **Supabase** (~99.9% each → ~99.8%
app-level). Spending to improve uptime should go to **a Railway replica** and a **Supabase
read path**, not to the render engines (already redundant).

**Cost of downtime buffer:** budget **~10–15% on top of render opex** for retries and
duplicate renders when an engine is flaky, plus **~$30–60/mo** for a standby Railway replica.

---

_Append new cost inputs / assumptions here as pricing or the engine mix changes._
