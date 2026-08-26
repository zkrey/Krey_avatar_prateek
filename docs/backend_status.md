# Krey backend — status update (2026-08-26)

**Repo:** `zkrey/Krey_avatar_prateek` · branch `claude/krey-avatar-setup-5ep7e2` · **81 tests passing.**

## ✅ Built — Service A (the digital-twin backend), GPU-free
- **Skin tone** — photo → Monk scale (1–10) + confidence. Verified on a real selfie (Monk 6, 0.87).
- **Body measurements** — pose keypoints + declared height → per-part measurements + confidence + accuracy ledger. Verified on a real body image (all 17 landmarks, sensible cm).
- **Eligibility gate** — one `canRender` wall: no account/DOB → blocked; **jurisdiction-keyed age policy** (India-only for M1; minors blocked even with consent); render-cost **token hold**.
- **Input cascade** — screens junk/unsafe photos cheapest-first (device → CPU) *before* the GPU; **capture-token anti-spam** (garbage earns 0).
- **Fit-score** — "does it fit?" rule engine (no GPU). Now **fit is measurement × preference**: fitted/true/relaxed/oversized, **per garment** → outfit combos; "try a size up/down" grading. Runs on real sample size charts.
- **Analytics** — every action emits a structured event (the spine + funnel), guest→user stitch, `gpu_seconds` for cost, social events schema-ready for M2. Wired into the live endpoints.
- **Recognition score** — the §6 "is this recognisably them" number in the record (backend-only, drives re-capture).

## 🔑 Key decisions locked
- **M1 render = generative (Path B)** + rule fit-score. **3D/Blender (Sohan) = M2 premium**, gated on the M1 fit-score hitting **~85% precision + fast on-phone render**.
- **Two accuracy axes:** twin *likeness* ~85% is fine (recognisable, not a mirror); product *fit* must be **exact** (misfit disliked unless asked).
- Forward-scope (M2 social · B2B in-store · scan-a-product · analytics) requirements captured in `docs/scope_bakeins.md`.

## ⏳ Not built yet
- **The render (Service B, generative try-on)** — the visual "you in a garment" + RAAQ. It's the GPU/cost piece; **parked** until a real GPU (local Intel integrated GPU can't run it). First step is a small paid benchmark.
- **Hair + eye attribute slices** — would lift the recognition score from 55% → 100% coverage. **Next up.**
- Dashboard / discovery / taste engine — broader app (master spec), separate workstream.

## Money
Nothing spent. Everything above is free/CPU. The only paid step ahead is the one-off GPU render benchmark, which we'll do deliberately.
