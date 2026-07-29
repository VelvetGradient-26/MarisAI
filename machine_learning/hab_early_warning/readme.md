# Problem A — Harmful Algal Bloom Early Warning

Implements section 3 of the ML Technical Approach. See
[`../README.md`](../README.md) for setup, the shared architecture, and results.

```bash
cd machine_learning
PYTHONPATH=. .venv/bin/python -m hab_early_warning.src.pipeline
```

Training takes ~13 minutes: three horizons x (four rolling-origin folds + a
final fit + isotonic calibration + SHAP) of LightGBM over 3.84M grid-cell-days
with 136 features. The built feature table is cached in
`data/processed/feature_store/hab_gridded.parquet`, so re-runs skip straight
to training unless you pass `--refresh-features` (rebuilding costs ~7 min).

Peak memory is ~2.5 GB. It was ~9 GB and OOM-killed before the feature store
was downcast to float32 and the fitting stride raised to 4 — worth knowing
before raising `TRAINING_STRIDE` back down or widening the region.

## Modules

| file | role |
|---|---|
| `src/labels.py` | forecast-then-threshold framing, weak percentile labels, t+3/t+5/t+7 targets (doc 3.1, 3.5) |
| `src/features.py` | growth rate, anomalies, nutrient ratios, stratification, upwelling, heatwave flag (doc 3.4) |
| `src/train.py` | rolling-origin CV with embargo, persistence baseline, calibration, SHAP (doc 3.6, 3.7) |
| `src/pipeline.py` | entry point |

## Framing

The model forecasts **chlorophyll**, and a bloom is declared where the
forecast exceeds a per-cell, per-season percentile threshold. Not a direct
binary classifier. This buys three things:

1. A continuous, explainable risk score — a trajectory plus a distance above
   local normal — rather than an opaque yes/no.
2. A threshold retunable per region, season or agency risk appetite **without
   retraining**.
3. Honesty about the label. A fixed global chlorophyll cutoff is not
   physically meaningful across regimes: 1 mg/m³ is an extreme anomaly in the
   open Arabian Sea and unremarkable in a coastal upwelling zone.

## Label strength — read this before quoting any metric

Everything here trains on a **weak label**: model chlorophyll above a high
local percentile is a *proxy* for a bloom. It is not a verified bloom, and it
says nothing about toxicity.

Two consequences:

- **The bloom rate is ~9.7%, not the "low single digits" the doc anticipates.**
  That is a property of the labelling rule, not of the ocean — a
  90th-percentile threshold yields ~10% positives by construction. Verified
  in-situ blooms are far rarer, and the class-imbalance strategy would need
  revisiting with them.
- **Stage 2 (harmful/toxic classification) is not implemented.** It needs
  in-situ genus and toxin data — HABSOS, NCCOS, HAEDAT, or INCOIS Algal Bloom
  Information Service advisories. None is openly queryable for this
  coastline. `labels.py` documents where strong labels would enter; the
  classifier is left unbuilt rather than faked on data that does not exist.

## Why the persistence baseline is on every fold — and what it found

"It is blooming now, so it will be blooming in three days" is a genuinely
strong forecast for a field this autocorrelated. Any model that cannot beat
it has demonstrated nothing. This is the internal stand-in for the doc's
external NOAA C-HARM / INCOIS benchmark, which needs data not openly
available here.

It earned its place twice over. On a first 2020-2021 run the model **lost** to
persistence at t+5 and t+7 — a result that would have been invisible without
the baseline, since the raw PR-AUC looked respectable. That finding drove the
window out to 2016-2021, after which the model beats persistence everywhere:

| horizon | model | persistence | verdict |
|---|---|---|---|
| t+3 | **0.661** | 0.511 | beats |
| t+5 | **0.493** | 0.384 | beats |
| t+7 | **0.362** | 0.309 | beats |

Note the current t+3 figure (0.661) is *lower* than the discarded one (0.755)
and is the trustworthy one — the old evaluation trained up to the test
boundary on a drifting label. Absolute values are not comparable across
evaluation setups. Full explanation in
[`../README.md`](../README.md#problem-a--hab-early-warning).

**Deployability differs sharply by horizon.** At 80% recall the false-alarm
rate is 0.55 at t+3 but 0.80 at t+7 — four in five week-ahead alerts are
false. t+3 is the horizon worth putting in front of an agency.

Probabilities are calibrated with isotonic regression fitted on the validation
slice (never on training, where the model is near-perfect, nor on test);
Brier improves 25-33% per horizon with ranking metrics unchanged.

## Wind stress

The Bakun upwelling index and Ekman pumping are computed from **observed**
scatterometer wind stress (`cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H`), not
from 10 m winds via a bulk formula, so no drag-coefficient assumption enters.
The earlier surface-current proxy is gone.

Wind contributes 14.4% of total |SHAP| at t+7 against chlorophyll's 36.8% —
real but secondary. The highest-ranked wind features are the *30-day rolling*
upwelling statistics rather than instantaneous values, which is the
physically expected shape: sustained upwelling drives nutrient supply, not
any single windy day.

Note the stress fields carry a fixed spatial mask covering ~39% of cells;
those rows keep their (fully populated) 10 m wind features and LightGBM
handles the missing stress natively.
