# Krey render — two engines: 2D generative vs 3D Blender

**One line:** there are two ways to make the "you wearing the garment" picture. We ship the
fast **2D generative** one first (M1), and Sohan's **3D Blender** one becomes the **premium**
tier (M2). Both are the *render* (**Service B**); neither is the twin+fit brain (**Service A**,
our repo). Right now we're proving the render engines *in isolation* before wiring them in.

---

## Path B — 2D generative try-on  ·  M1, ship first

- **What:** a diffusion model (CatVTON / IDM-VTON) takes a **person photo + a garment
  product image** → outputs a 2D image of that person wearing it.
- **Why first:** fast, cheap-ish, and works on **any garment product image** — so it scales to
  open inventory (any shop's catalogue photo), no per-garment 3D asset needed. Good enough to
  build the habit (the everyday try-on play loop).
- **Inputs:** person photo (or a twin frame) + garment **product image** (flat-lay / on-model /
  ghost-mannequin). **Not** sewing patterns.
- **Cost/speed:** measured ~**16.6 GPU-s ≈ ₹1.6/render** on cloud (IDM-VTON, 30 steps). We're
  now testing **CatVTON on Sohan's local GPU** to get a cheaper/faster number for free.
- **Honest limit:** it's a 2D "skin" — it flatters, and can be slightly off on drape. That's
  fine, because the **fit *truth* comes from our rule fit-score** (Service A), computed
  separately. The render is the pretty picture; the fit-score is the truth.

## Path A — 3D sew + cloth-physics  ·  M2, premium  ·  Sohan's work

- **What:** in Blender, 2D garment **sewing patterns** (front/back panels) are stitched and
  **cloth-simulated** onto a 3D body → a physically-accurate **3D drape**.
- **Why premium:** true-to-physics fit, made-to-measure accuracy, rotate/zoom, the "wow" for
  high-intent moments. Genuinely differentiated — most try-on apps can't do real drape.
- **Inputs:** 2D sewing patterns (Sohan's panels) + a 3D body derived from **our measurements**
  (Service A's twin).
- **Honest limit:** heavier (3D sim + render) and needs **per-garment 3D asset prep**, so it
  doesn't scale to open inventory like 2D does. It's a premium/curated engine, not every garment.
- **Gate:** deferred to **M2**, unlocked once the M1 rule fit-score reaches **~85% precision** —
  the 3D drape is only worth it if the underlying body measurements are accurate enough.

---

## How both relate to our code (Service A)

Service A (built, 272 tests) is the **twin + fit brain**: photos → skin tone / hair / eye /
measurements / identity, the **fit-score** (does it fit, what size), and tokens/eligibility.
**Service A does not render.** Both render paths are **Service B** options, and **neither is
wired to Service A yet** — that's the next step once we pick and prove an engine.

```
Service A (our code): build twin + fit-score + token gate
        │  passes person + garment
        ▼
Service B (the render): Path B (2D generative) now  ·  Path A (3D Blender) later, premium
        │
        ▼
fit-score tells the TRUTH about fit; the render shows the PICTURE
```

`/render/authorize` (tokens/entitlements, already built) gates the render; the fit-score
(already built) is what keeps us honest regardless of which render engine draws the image.

## Plan ahead (sequence)

1. **Now** — prove **Path B on Sohan's GPU** (CatVTON): get one render, measure local speed.
   De-risks the engine, ₹0.
2. **Next (M1 render build)** — pick the 2D engine, wrap it as a **Service B endpoint**, wire it
   to Service A (`/render/authorize` + fit-score). Optimize steps + add caching for cost.
3. **Parallel (Sohan, M2 track)** — keep building the **Blender 3D sew+sim** pipeline as the
   premium engine. Define the interface: our twin measurements → his 3D body; a garment → a
   reusable 3D asset.
4. **M2 gate** — when the fit-score hits ~85%, integrate **Path A** as the premium (token-pass)
   tier alongside the 2D one.

## Sohan's lane (what to focus on)

- **Own the 3D drape pipeline (Path A)** — pattern → sew → cloth-sim → render — as the premium
  engine. This is the differentiated, hard-to-copy part.
- **Today:** help prove **Path B** (CatVTON) works + measure it — a useful benchmark for the
  whole team, and it tells us the cheap-render floor.
- **Interface to define with us:** how our **measurement twin** becomes the 3D body he drapes
  on, and how a garment becomes a **reusable 3D asset** (so the 3D path can scale beyond one-offs).
