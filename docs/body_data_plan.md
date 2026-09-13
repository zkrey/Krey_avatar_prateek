# Body data plan — shape & Indian anthropometrics

Like skin tone, **body shape is deterministic — no training.** `app/measure_core.classify_body_shape`
already classifies from bust/waist/hip/shoulder ratios, sex-aware, into our taxonomy
(hourglass / triangle(pear) / round(apple) / rectangle / inverted). The shared
`classify_body_shape(bust,waist,hip,shoulder)` snippet is the **same logic** — it validates
ours, it doesn't add a model. So the Indian body resources feed **calibration + validation**,
not training.

## What the Indian anthropometrics actually calibrate
[IndiaSize](https://www.scribd.com/document/850449371/indiasize) (India's national sizing
survey) and [Indian Anthropometric Dimensions](https://www.scribd.com/document/511496232/INDIAN-Anthropometric-Dimensions)
are **measurement reference tables**, not image datasets. Use them to move three sets of
constants from *sample* to *real, Indian-first*:
- **Size charts** — `app/config/size_charts.json` (currently sample charts) → real Indian
  garment size bands. This is the biggest fit lever.
- **Plausibility ranges** — `measure_core.PLAUSIBLE_CIRC_CM` (the guardrails that gate a
  measurement as believable) → widen/centre for the Indian population.
- **Depth ratios** — `measure_core.DEFAULT_DEPTH_RATIO` (front-only depth = width × ratio) →
  Indian-population depth priors improve the single-photo circumference estimate.

> Scribd links are secondary copies — get the **authoritative IndiaSize / BIS source** and
> confirm licence before using the numbers in a shipped product.

## Hard guardrail (doctrine): population data calibrates, it never priors a person
Compute an individual's shape and measurements from **their** photo, always. Use Indian
anthropometrics only to calibrate charts / ranges / depth priors — **never** to bias a
specific person's shape or size by ethnicity. Same discipline as the eye-colour Indian prior
(a tie-breaker only). Fit must be exact; a population prior on the individual would break that.

## South-Asian shape notes (as validation expectations, not overrides)
Documented tendencies — Rectangle common; Pear common in South-Asian females; higher central
adiposity (Apple / **WHtR > 0.5**) risk. Use these to **sanity-check** the distribution the
pipeline produces on Indian data (the report below), not to relabel anyone. WHtR (waist ÷
height) is a useful derived health/shape signal we can surface later; it is not a shape class.

## Tooling (in the repo)
- **Report:** `python -m bench.body_shape_report --csv data/indiasize/adults.csv --name indiasize`
  runs OUR classifier over an anthropometric CSV → `data/reports/<name>.{json,md}`: shape
  distribution, WHR/WHtR summaries, and the **out-of-plausible-range rate** (what to widen in
  `PLAUSIBLE_CIRC_CM` for Indian bodies). Registry: `data/sources.json`.
- The two references are **not auto-fetchable** (Scribd/login) — add the CSVs to
  `data/indiasize/` manually, then run the report.

## Still needs the pipeline (separate from tabular calibration)
Validating the **measurement pipeline itself** (photo → circumferences) needs the pose model
and real full-body captures — casual photos have wide error bars (`docs/scope_bakeins.md`),
so fit-grade needs a **guided capture**. The alpha `/body/measure` path + guided capture is
where that ground truth comes from; IndiaSize calibrates the *charts and ranges* those numbers
are compared against.

## Recommendation
1. Get the authoritative IndiaSize/BIS tables; export CSVs into `data/indiasize/`.
2. Run `bench.body_shape_report` → recalibrate `size_charts.json`, `PLAUSIBLE_CIRC_CM`, and
   `DEFAULT_DEPTH_RATIO` for Indian bodies (sample → real).
3. Keep body shape deterministic; validate the distribution vs the South-Asian expectations
   above; never prior an individual.
