# data/indiasize/ — body-shape calibration input

Drop real **IndiaSize / BIS** anthropometric rows here as **`adults.csv`**, then run the
body-shape report. `adults.template.csv` shows the exact schema (its rows are **illustrative,
not real data**). Real CSVs you add here are git-ignored; only the template + this README are
tracked.

## Schema (`adults.csv`)
Columns are case-insensitive; measurements in **cm**. Extra columns are ignored.

| Column | Meaning | Required |
|---|---|---|
| `chest` (or `bust`) | chest/bust circumference | yes (or shoulder) |
| `waist` | waist circumference | **yes** |
| `hip` | hip circumference | **yes** |
| `shoulder` | shoulder **width** | optional (used if chest missing) |
| `sex` | 1 = male, 2 = female | optional (default 2) |
| `height` | stature (for WHtR) | optional |

## Run
```
python -m bench.body_shape_report --csv data/indiasize/adults.csv --name indiasize
# -> data/reports/indiasize.{json,md}
```
The report gives the **shape distribution**, **WHR/WHtR** summaries, and the **out-of-plausible-range
rate** — that last number is what to widen in `app/measure_core.PLAUSIBLE_CIRC_CM`, alongside
recalibrating `app/config/size_charts.json` and `DEFAULT_DEPTH_RATIO` for Indian bodies.
Rationale + guardrails (never prior an individual by ethnicity): `docs/body_data_plan.md`.

`data/reports/indiasize_template.md` is a sample report generated from the template rows, so
you can see the output shape before the real tables land.
