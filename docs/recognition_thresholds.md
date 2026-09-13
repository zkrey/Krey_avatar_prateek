# Recognition thresholds — the 85% bet, and what the literature backs

Why the twin targets are set where they are, what's an engineering benchmark vs a
published constant, and how to validate them on real users. Numbers here are
**provisional** — the alpha tester's flag data is the instrument that finalises them.

## The targets we set (current)

| Signal | Target | In code |
|---|---|---|
| Twin **likeness** (recognisably you) | **~85%** | `docs/backend_status.md`, `config/recognition.json` |
| Product **fit** | **exact** (not a rate) | `docs/backend_status.md` |
| Recognition **recapture floor** | **0.60** | `app/recognition.py`, `config/recognition.json` |
| Identity soft-confirm ladder | accept **≥0.60** · reconfirm **0.35–0.60** · retake **<0.35** | `app/capture_core.py` |
| Capture set | **5** photos | `app/capture_core.py` (`target_frames=5`) |

**Where 85% comes from:** it's an **engineering benchmark**, not a literature constant —
≈75% assumed human self-identification + a ~10% buffer. Humans don't perceive their own
body as a mirror, so a recognisable twin (not a pixel-perfect one) is enough to build the
habit; the soft-confirm + flag loop closes the rest cheaply. The literature supports the
*shape* of this bet, per attribute — not the exact 85%.

## What the literature actually says

**Body weight / shape — the closest evidence.** Piryankova et al. (2014), *Can I Recognize
My Body's Weight?* People accept a **band** of BMI-distorted self-avatars as "me" (reported
range ≈ **+0.83% to −6% BMI**), biased toward accepting *thinner*; **photo-realistic texture
matters** (untextured avatars had to be made thinner to read as self). → tolerance bands are
real; no 100% mirror needed.

**Self-perception is already sub-100%.** Rapid body-size judgments ≈ **69% at 17 ms**;
silhouette recognition ≈ **41%** in comparative tasks; self-*reported* height overestimated
by ≈ **1.2 cm**, weight under-reported by women. → a ~70–75% human baseline is defensible,
though highly task-dependent.

**Measure in percent, not cm (Weber's law).** JND for body dimensions scales with magnitude;
percent error tracks perception better than absolute cm. → keep per-field thresholds
proportional (the backend already carries percent confidence).

**Skin tone has a hard metric — CIELAB ΔE.** JND ≈ **ΔE 1** (technical ~2.3); **ΔE ≤ 2** is
the accepted bar for skin, which people judge strictly (a "memory colour"). → set the skin
target as **ΔE ≲ 2–3 vs reality**, not a Monk-bucket match. This is why the coarse-bucket bug
(two distinct people both "Monk 6") was fixed by carrying **continuous** tone.

**Height** is the declared scale anchor, so it isn't a perceptual-recognition problem — it's
self-report noise (±~1.2 cm), well within tolerance.

## Implications for Krey

- **85% likeness** is a reasonable launch bet; treat it as provisional and measure it.
- **Skin** target is quantifiable now: continuous tone, aim ΔE ≲ 2–3.
- **Weight/shape** has a tolerance band — surface confidence + a soft reconfirm rather than
  demanding accuracy; never hard-reject (doctrine: no forced cost).
- **Recognition weights** (`config/recognition.json`: skin .30 · hair-colour .25 ·
  landmark .25 · eye .10 · texture .10) are `v0-provisional` — recalibrate against flag data.

## How we validate it (the tester is the study)

The alpha Twin Check (`/alpha`) is a self-recognition experiment: every **flag** is a
"that's not me / that's wrong" signal per attribute, and every **confirm** is agreement. The
distribution of flags vs shown-value gives the real threshold at which users reject each
attribute — that's what replaces the 85% assumption with a measured number.

## Sources

- Piryankova et al., *Can I Recognize My Body's Weight?* — ACM TAP: https://dl.acm.org/doi/10.1145/2641568
- Photo-realistic self-avatars from 3D body scans — Frontiers: https://www.frontiersin.org/journals/ict/articles/10.3389/fict.2018.00018/full
- Body size judgments at 17 ms — PMC: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6978682/
- Self-reported anthropometric accuracy (Finnish Twin) — PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC9234778/
- Self-perception of weight and height — IJERPH: https://doi.org/10.3390/ijerph18168502
- Online psychophysical body-image perception / JND — PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC11164378/
- Delta E perception categories — Konica Minolta: https://sensing.konicaminolta.eu/mi-en/colourblogtop/colour-blog/whatisdeltae
- Skin-colour classification with CIELAB — Color Research & Application: https://onlinelibrary.wiley.com/doi/full/10.1002/col.70012
