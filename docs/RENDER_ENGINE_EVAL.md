# Krey — Render Engine Evaluation (deep dive + frontier survey)

_A current (2026-10) read of the virtual-try-on / person+garment generation field,
scored against our own ceilings in [`MODEL_CHALLENGES.md`](./MODEL_CHALLENGES.md).
Deep dive on the two engines we actually run — **CatVTON** and **Nano Banana** —
plus the other frontier options worth knowing about. Pull this when picking what to
route to, or what to benchmark the owned model against._

> **Bottom line up front:** the render engine is a **commodity** and the field has
> already passed the "assembled open-source VTON" era. The honest 2026 ranking for
> *our* job (casual IG-native photo + catalog garment → faithful, same-person, fast):
> **Nano Banana (Gemini 2.5 Flash Image) > FASHN v1.6 ≈ Kling/Kolors > CatVTON >
> SDXL+InstantID.** We should stop trying to out-engineer the render and instead
> **auto-route** to the best available, keep CatVTON as the free/private fallback,
> and spend the real effort on the ranking/confidence moat + the data that trains the
> owned model later.

---

## 1. Deep dive — CatVTON (what we run as default)

**What it is:** SD-1.5 inpaint + DensePose/SCHP AutoMasker; ~49.6M trainable params
(it only fine-tunes the self-attention of the U-Net — that's why it's small/cheap).
Self-hosted on Modal T4, fire-and-poll.

**Strengths (confirmed by the field, not just us):**
- **Faithful to the real photo** — it inpaints the garment onto the actual body/scene,
  so it's honest (no invented person, no invented background). Good for validation.
- **The only common open model that survives non-standard poses** — sitting, lying,
  arm-up, off-axis — because it works on the real image rather than regenerating a
  catalog-style portrait. That matters for IG-native input (our C1).
- Efficient: small model, cheapest to self-host, no per-image vendor fee.

**Ceilings (confirmed):**
- **Flattens fabric.** It renders plausible-but-generic surfaces and *misses texture
  on complex garments* — sequins, silk, heavy print. (Our C2 garment fidelity.)
- **2D warp, not 3D drape** — stretched collars/torsos (our C4).
- **OOD-fragile on parsing** — if DensePose/SCHP mislocate the body (EXIF-rotated,
  cropped, group shots), the whole render fails (our C1). We patched EXIF + cloth-type
  crop, but the parser is the ceiling.
- **Slow cold** — 172–344s on a cold T4 (scale-to-zero + ~5GB load + 40 steps) (C8).
- Needs a reasonably clean body photo to shine.

**Verdict:** keep it. It's our free, private, pose-robust fallback and our honesty
baseline. It is **not** the quality leader and never will be — it's a 2024-class
architecture.

---

## 2. Deep dive — Nano Banana (Gemini 2.5 Flash Image)

**What it is:** Google's `gemini-2.5-flash-image` (released Aug 2025). Closed, paid,
API-only. Ingests the **person image + garment image(s) + a text instruction** and
composes them in **one pass**.

**Why it's ahead (confirmed externally):**
- Hit **#1 on LMArena's Image-Edit and Text-to-Image** leaderboards at launch with a
  large preference lead.
- **Character/identity consistency across edits** and **multi-image fusion** are its
  headline strengths — exactly the two things our assembled stack fails (C2 + C3).
- **~seconds** latency, photorealistic, single-pass (C8).
- **This is literally the model Google shipped try-on with.** Google's **Doppl** app
  and now **Google Search/Shopping virtual try-on** are powered by Gemini 2.5 Flash
  Image. So the "frontier try-on" and "our beta render path" are the *same model* —
  we don't need to chase Doppl, we can call its engine directly.

**Ceilings / risks:**
- **Closed + paid + per-image** (C11) and **user body photos leave our infra** — a
  real privacy concern for a body/identity product. Surface it to users; it's the
  strategic reason to own a model eventually.
- **Blocked for us on billing** — the free tier is 0 image quota; needs the Google
  **Cloud** project on paid billing (Google One ≠ API billing). Code + key are wired;
  flip billing and it works with no redeploy.
- Vendor pricing/availability risk; instruction-following try-on isn't a dedicated
  VTON endpoint (it's a general image model prompted for try-on), so garment fidelity
  is very good but not *guaranteed* pixel-exact the way a trained VTON can be.
- **Successor exists:** "Nano Banana Pro" = Gemini 3 Pro Image — higher tier, higher
  cost. Worth testing once billing is on, but 2.5 Flash Image is the price/quality
  sweet spot for us.

**Verdict:** this is the quality answer for IG-native input, and it's the same engine
Google productionized. Priority unblock = **turn on Cloud billing.**

---

## 3. Frontier survey — the other options (2026)

The market has consolidated onto a few pay-per-use APIs (mostly reachable via **fal**)
plus a handful of open models. Scored for *our* job.

### Hosted / API (production-ready today)
| Model | Takes garment img? | Price (approx) | Latency | Strength | Weakness |
|---|---|---|---|---|---|
| **Nano Banana** (Gemini 2.5 Flash Image) | ✅ + person + text | per-image, paid | ~sec | identity + multi-image fusion, #1 edit quality; powers Google try-on | closed, privacy, billing-gated |
| **FASHN v1.6** | ✅ on-model + flat-lay | ~$0.075/gen (Max $0.15–0.375); ~$0.049 at tiers | 7s / 10s / 19s modes | **best fabric texture + print/logo fidelity** — catalog-grade | mixed lower-body fidelity |
| **Kling / Kolors v1.5** | ✅ | ~$0.07/gen | fast | holds **pose, skin tone, body shape** well | sometimes flattens garment detail |
| **FLUX Virtual Try-On Pro** | ✅ + styling prompt | paid (fal) | — | **prompt-directs how it's worn** (tucked, sleeves rolled) | general-image lineage, less VTON-specialized |
| **Google Search/Shopping try-on** | ✅ (retailer catalog) | consumer, no API | — | consumer reach | **no public API**, retailer-catalog only, no lingerie/swim |

### Open-source / self-hostable
| Model | Notes for us |
|---|---|
| **IDM-VTON** | Free with a GPU; strong garment detail; the common open baseline. A real step up from CatVTON on fidelity if we want to stay self-hosted. |
| **OOTDiffusion** | **Best open garment fidelity / detail**, but slow and needs **16–24GB VRAM** (→ L4/A10 class, not T4). Quality-for-cost tradeoff. |
| **Leffa** | Explicit upper/lower/dress typing; fixed the texture-distortion problem of earlier diffusion VTON; weakness = bottom detection + old-garment silhouette bleed. |

### Research frontier (not productionizable yet, but the bar our owned model targets)
- **Oxygen-TryOn** — fashion-native *foundation model* for any-item try-on.
- **Tstars-Tryon 1.0** — robustness + diversity across item types (our C6).
- **FitVTON** — **fit-aware** try-on with body–garment *size* control (our C4 fit).
- **JCo-MVTON** — mask-free multi-modal DiT (removes the AutoMasker dependency that
  breaks CatVTON on OOD input — our C1).
- Benchmarks to evaluate against: **VTBench**, **OpenVTON-Bench**, **Garments2Look**
  (multi-reference, accessories).

---

## 4. Scored against our ceilings (MODEL_CHALLENGES.md)

| Ceiling | CatVTON | Nano Banana | FASHN | Kolors | IDM/OOTD (open) |
|---|---|---|---|---|---|
| C1 OOD/IG poses | ⚠️ real-photo helps, parser breaks | ✅ best | ⚠️ catalog-ish | ⚠️ | ❌ |
| C2 garment fidelity | ❌ flattens | ✅ | ✅ **best** | ⚠️ | ✅ (OOTD) |
| C3 identity twin | ✅ (it's the real photo) | ✅ strong | ✅ (real photo) | ✅ | ✅ (real photo) |
| C4 3D fit/drape | ❌ 2D warp | ⚠️ learned, not true 3D | ⚠️ | ✅ pose/body | ⚠️ |
| C5 skin synthesis (coverage change) | ❌ | ✅ | ⚠️ | ✅ skin tone | ⚠️ |
| C6 non-Western/diversity | ❌ | ⚠️ better, untested on saree | ⚠️ | ⚠️ | ❌ |
| C7 multi-piece sets | ❌ | ⚠️ one-pass helps | ⚠️ | ⚠️ | ❌ |
| C8 latency/cost | ❌ cold 170–340s | ✅ ~sec, paid | ✅ 7–19s | ✅ fast | ⚠️ heavy VRAM |
| C11 owned/private | ✅ owned | ❌ closed, data leaves | ❌ | ❌ | ✅ owned |

**Read:** no single engine clears every ceiling — which is the whole thesis of
MODEL_CHALLENGES.md. Nano Banana wins quality/identity; CatVTON & open models win
ownership/privacy; FASHN wins pure garment fidelity.

---

## 4b. Why this ordering (Nano Banana ≫ FASHN ≈ Kolors > CatVTON > InstantID)

The ranking is two axes stacked: a **quality/architecture axis** (reasoning model >
trained VTON > inpaint-warp > text-conditioned stylizer) and a **fitness-for-our-job
axis** (must show the *real garment* on the *real person*, faithfully, consistently,
on casual IG input). Here's each step.

### Nano Banana ≫ everything (a step-change, not a nudge)
- **Only one that reasons over person + garment + instruction in one pass.** The others
  *warp* a garment onto a parsed body region; Nano Banana *regenerates* the scene
  understanding what it sees — so "this person, in this kurta, 80s vibe" is a single
  coherent intent, not mask-and-paste.
- **Identity consistency is its headline benchmark win** (#1 LMArena image-edit at
  launch). That's our C3 (true twin) *and* C10 (same person across looks so voters
  judge the garment, not render noise) — the two things that make peer ranking fair.
- **Multi-image fusion** holds person *and* garment together — the exact failure of our
  InstantID path (garment was text-only).
- **Survives OOD/IG input** (arm-up, cropped, group) — not dependent on a DensePose/SCHP
  parser that falls over off-axis (our C1, the #1 product constraint).
- **External validation:** Google shipped Doppl and now Search/Shopping try-on on *this
  exact model*. The frontier try-on product and our beta path are the same engine.
- **The one caveat:** it's a general image model prompted for try-on, not a trained VTON
  head — garment fidelity is excellent but not *guaranteed* pixel-exact on a logo/print
  the way a dedicated VTON can be. Plus closed, paid, body photo leaves our infra.

### FASHN ≈ Kolors (the `≈` is deliberate — they trade blows)
Both are production VTON specialists (via fal), both take a garment image, both ~$0.07/
gen, both seconds-fast. A tier *below* Nano Banana (they warp, don't reason), a tier
*above* CatVTON (modern architecture, far more training data). Between the two:
- **FASHN wins on garment fidelity** — best-in-category fabric texture, print, logo
  (864×1296). Weakness: mixed lower-body fidelity. → pick when the *garment* is the hero.
- **Kolors wins on the body** — holds pose, skin tone, body shape most reliably.
  Weakness: sometimes flattens garment detail. → pick when the *body/pose* is the risk.
- Opposite failure modes, neither dominates → `≈`. (FLUX Try-On Pro sits here too, with
  styling-prompt control — tucked/sleeves — but less VTON-specialized.) Both still trail
  Nano Banana on identity and true casual-input robustness.

### CatVTON (fourth — and honestly so)
Below the hosted specialists because it's a **2024-class architecture** (SD-1.5 inpaint +
~49.6M-param self-attention fine-tune): flattens fabric (C2), 2D warp not 3D drape (C4),
parser-fragile on OOD (C1), slow cold 172–344s (C8). **But above InstantID, and we keep
it,** for two non-negotiables: (1) it inpaints onto the *real photo* → identity perfect
by construction, output honest (no invented person/background); (2) it's the **only one
of the five that survives non-standard poses** (sitting/lying/arm-up) because it works on
the real image, not a regenerated portrait. Also **free and private** (self-hosted, body
photo never leaves our infra — the thing every hosted option sacrifices). → free/private
fallback + honesty baseline.

### SDXL + InstantID (last — structurally wrong for try-on)
Not just lower-quality, architecturally mismatched:
- **Takes the garment as text only** → literally cannot reproduce a specific garment
  (invented a feather dress for a cream kurta). Fails C2 at the root — and C2 is half the
  product.
- **Identity collapses as the face shrinks in frame** — one-shot face adapters are weak
  at body framing, so at "head-and-shoulders wearing X" scale the base model's face prior
  takes over → generic person (fails C3).
- Its real strength (stylised "80s vibe") is a *look*, not a *try-on* — it answers "make
  a cool stylised portrait," not "show me this garment on me," which is the question the
  ranking loop depends on.

---

## 5. Recommendation (what to actually do)

1. **Stop out-engineering the render.** It's a commodity and the field proves it —
   Google itself ships try-on on the same Gemini model we already wired.
2. **Unblock Nano Banana** (Google Cloud billing) and make it the quality path for
   IG-native uploads. Code is ready.
3. **Keep CatVTON** as the free, private, pose-robust fallback / honesty baseline.
4. **Auto-route, don't make the user choose:** clean body shot → CatVTON (free);
   casual/IG input or "make it look great" → Nano Banana. Hide the engine names.
5. **Shortlist one hosted VTON specialist to A/B** when garment fidelity is the
   priority (catalog logos/prints): **FASHN v1.6** (best texture) via fal, as a drop-in
   alongside banana.py. One stdlib client, same fire-or-sync pattern.
6. **If we ever want a better *owned* engine before the from-scratch model:** the
   cheapest upgrade from CatVTON is **IDM-VTON / OOTDiffusion** on an L4 (more VRAM,
   better fidelity) — still self-hosted, still private.
7. **Benchmark the eventual owned model** against VTBench / OpenVTON-Bench and the
   research frontier (Oxygen-TryOn, FitVTON, JCo-MVTON), not against CatVTON.

The energy stays on the **ranking/confidence/network moat** and the **data capture**
that trains the owned model — the render is rented until then.

---

## Sources (2026-10 survey)
- fal — [10 Best Virtual Try-On APIs in 2026](https://fal.ai/learn/tools/best-virtual-try-on-apis-2026) (FASHN/Kolors/FLUX pricing + latency)
- FASHN — [comparing top open-source VTON models](https://fashn.ai/blog/comparing-the-top-4-open-source-virtual-try-on-viton-models), [API](https://fashn.ai/products/api)
- fashiolabs — [Open-Source VTON Compared: IDM-VTON, OOTDiffusion, ViTON (2026)](https://fashiolabs.com/blog/open-source-virtual-try-on-compared)
- ionio — [CatVTON vs Kling vs FASHN vs Qwen vs Nano Banana](https://www.ionio.ai/blog/vton)
- CometAPI — [Gemini 2.5 Flash Image (Nano Banana) feature + benchmark](https://www.cometapi.com/gemini-2-5-flash-imagenano-banana-feature-benchmark-and-usage/)
- Tigris — [Flux Kontext vs Nano Banana](https://www.tigrisdata.com/blog/flux-kontext-vs-nano-banana/)
- OpenRouter — [Nano Banana API pricing & benchmarks](https://openrouter.ai/google/gemini-2.5-flash-image)
- Google — [Nano Banana image generation docs](https://ai.google.dev/gemini-api/docs/image-generation)
- WebProNews — [Google launches Doppl](https://www.webpronews.com/google-launches-doppl-ai-virtual-try-ons-transform-online-shopping/); happycapyguide — [Doppl shutdown → try-on moves into Search](https://happycapyguide.com/blog/google-doppl-shutdown-ai-virtual-try-on-search-retail-2026)
- arXiv — [Oxygen-TryOn](https://arxiv.org/pdf/2607.21694), [Tstars-Tryon 1.0](https://arxiv.org/pdf/2604.19748), [FitVTON](https://arxiv.org/pdf/2606.12012), [JCo-MVTON](https://arxiv.org/pdf/2508.17614), [OpenVTON-Bench](https://arxiv.org/pdf/2601.22725), [VTBench](https://arxiv.org/pdf/2505.19571)
</content>
</invoke>
