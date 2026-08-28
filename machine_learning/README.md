# Maris AI — Machine Learning

Implementation of the *Maris AI ML Technical Approach* document
(`Artifacts/Maris_AI_ML_Technical_Approach.pdf`) for the two problem
statements:

- **Problem A — Harmful Algal Bloom (HAB) early warning** → `hab_early_warning/`
- **Problem B — Fish habitat / Potential Fishing Zone (PFZ)** → `fish_habitat_prediction/`

Both sit on one shared **Marine Data Fusion Layer** (`marine_ml/`), exactly as
section 5 of the doc specifies: single ingestion path, single feature store,
single set of geometry utilities, single validation harness. Only labels and
problem-specific derived features diverge.

Current scope is **Tier 1 + Tier 2** of the doc's model hierarchy. Tier 3
(ConvLSTM / Vision-Transformer spatio-temporal models) is deliberately not
implemented — see [What is deliberately not here](#what-is-deliberately-not-here).

---

## Layout

```
machine_learning/
├── marine_ml/                    # shared spine — both problems import this
│   ├── config.py                 # region, grid, windows, dataset ids, paths, credentials
│   ├── sources/                  # raw-zone ingestion, one module per source
│   │   ├── copernicus.py         #   physics + biogeochemistry reanalysis
│   │   ├── gebco.py              #   bathymetry / seafloor slope
│   │   └── obis.py               #   species occurrence + target-group pool
│   ├── fusion.py                 # regrid + QC + the shared feature store
│   ├── features/
│   │   ├── geometry.py           #   fronts, Okubo-Weiss, upwelling, distance-to-coast
│   │   └── temporal.py           #   climatology/anomalies, lags, rolling, cyclical
│   └── validation/
│       ├── splits.py             #   rolling-origin, spatial block, leave-one-region-out
│       └── metrics.py            #   PR-AUC, TSS, Boyce, Brier, reliability, MESS
├── hab_early_warning/src/        # Problem A
│   ├── labels.py                 #   forecast-then-threshold, weak labels, multi-horizon
│   ├── features.py               #   growth rate, nutrient ratios, stratification, upwelling
│   ├── train.py                  #   rolling-origin CV + persistence baseline + SHAP
│   └── pipeline.py               #   entry point
├── fish_habitat_prediction/src/  # Problem B
│   ├── labels.py                 #   thinning + target-group pseudo-absence
│   ├── features.py               #   fronts, prey lag, thermal niche, bathymetric context
│   ├── models.py                 #   MaxEnt / Random Forest / LightGBM + ensemble
│   ├── train.py                  #   spatial block CV + SHAP
│   └── pipeline.py               #   entry point
├── scripts/fetch_raw.py          # populate the raw zone
├── data/                         # raw / interim / processed (gitignored)
├── models/                       # fitted artifacts
└── reports/                      # fold scores, holdout metrics, SHAP, calibration
```

## Setup

```bash
cd machine_learning
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Copernicus credentials are read from the backend's untracked `backend/.env`
(`COPERNICUS_USERNAME` / `COPERNICUS_PASSWORD`) — there is no second place to
put secrets. A `machine_learning/.env` is also honoured if you prefer to keep
them separate.

## Running

```bash
cd machine_learning
export PYTHONPATH=.

.venv/bin/python scripts/fetch_raw.py              # ~4 min, ~840 MB
.venv/bin/python -m fish_habitat_prediction.src.pipeline   # ~1 min
.venv/bin/python -m hab_early_warning.src.pipeline         # ~40 min (LightGBM on 1.3M rows)
```

Both pipelines cache their built feature table in
`data/processed/feature_store/` and reuse it; pass `--refresh-features` to
rebuild.

---

## Experiment tracking

Every report in this repo is written to a **fixed filename** —
`reports/fish_habitat_shap.csv`, `reports/hab_early_warning_summary.json`, the
backend's `_reports/training_report.json` — so each rerun destroys the one
before it. That made "did that change help?" unanswerable, which made every
modelling improvement unmeasurable. `marine_ml/tracking.py` is the fix: runs
are appended and never overwritten.

Nothing extra to do for the two pipelines — they log automatically when they
save. To browse:

```bash
cd machine_learning
uvx --from mlflow mlflow ui --backend-store-uri sqlite:///mlruns.db
```

The **backend forecasting engine** is tracked too, but indirectly. `backend/`
must not gain an MLflow dependency (keeping the modelling stack out of the
API's import graph is deliberate), so it writes plain JSON and this side reads
it:

```bash
.venv/bin/python -m marine_ml.ingest_forecasting     # after any training batch
.venv/bin/python -m marine_ml.ingest_forecasting --dry-run
```

Ingestion is idempotent — a run is keyed by `(variable, horizon, trained_at)`,
so re-running after every batch is safe, and a *retrain* correctly appears as a
new run rather than replacing the old one.

Three things worth knowing:

- **`mlflow-skinny`, not `mlflow`.** The full package pins `pandas<3` and
  `pyarrow<23`; installing it downgrades this environment from pandas 3.0.5 /
  pyarrow 25, a major-version pandas downgrade underneath a 3.9M-row parquet
  feature store. Skinny plus SQLAlchemy is the whole tracking client with none
  of that. The UI runs via `uvx` above, so it never enters this venv.
- **Tracking never fails a training run.** A HAB run is ~40 minutes; losing it
  to a locked store would be worse than not tracking. Every entry point
  degrades to a warning. Set `MARINE_ML_TRACKING=0` to opt out entirely.
- **Fold *spread* is logged, not just the mean.** `cv_<metric>_min`/`_max`/
  `_std` sit beside `_mean`, because a healthy average over folds that include
  negatives is the specific failure this project keeps hitting — four
  forecasting horizons printed `beats persistence` on their aggregate while
  failing on folds. `passes_bar` encodes the shipping rule directly: overall
  skill > 0 **and** at most one of five folds negative.

---

## The two fetch profiles, and why they differ

The doc asks for one feature store. It also asks for resolution-aware
regridding per region. Those pull in opposite directions here, and the
resolution was driven by measurement rather than preference:

| | Problem B (habitat) | Problem A (HAB) |
|---|---|---|
| Region | North Indian Ocean, 55–95°E / 5°S–25°N | Arabian Sea, 68–78°E / 6–23°N |
| Cadence | monthly | daily |
| Window | 2000–2013 | 2016–2021 |
| Sources | physics, BGC, bathymetry, OBIS | physics, BGC, **wind stress**, bathymetry |
| Bound by | **label availability** | **interannual variability** |

- **Problem B's window is set by OBIS, not Copernicus.** Target-species
  occurrence records in this region are concentrated in 2000–2013 and
  effectively stop after 2014 (~1,130 records across five species in-window,
  single digits after). Training on 2016–2021 environmental fields would mean
  fields with no labels attached. Monthly cadence is also the honest match:
  occurrence records carry imprecise dates, so daily fields would be false
  precision.
- **Problem A's window is set by how many monsoon seasons it needs to see.**
  Daily fields are non-negotiable for a t+3/t+5/t+7 forecast, so the region
  gives instead. The span was originally 2 years on fetch-cost grounds and had
  to grow — see [Why the window changed](#why-the-window-changed).

Wind is HAB-only. The habitat pipeline runs on monthly means where daily wind
stress has no meaning, and `build_gridded_frame(wind=...)` is optional
precisely so that omitting it changes nothing else.

Both profiles run through the same ingestion, fusion and feature code. The
shared-spine guarantee is that a feature means the same thing in both, not
that both cover the same box.

## Measured fetch performance

Established empirically, because picking the wrong Copernicus service or
forgetting the depth bound turns seconds into hours:

| product | request | time |
|---|---|---|
| physics 1/12° daily | 8×14° box, 30 days | ~63 s |
| physics 1/12° daily | 10×17° box, 2 years | ~60 s |
| physics 1/12° monthly | 40×30° box, 14 years | ~76 s |
| bgc 1/4° daily | 10×17° box, 2 years | ~24 s |
| bgc 1/4° monthly | 40×30° box, 14 years | ~34 s |
| wind 1/8° **hourly** | 10×17° box, 1 month | ~85 s (324 MB) |

Wind is the outlier and dictates its own fetch strategy: the only multi-year
product is hourly, so six years is ~7.8 GB in memory to produce ~160 MB of
daily means. `fetch_wind` therefore requests one calendar month at a time and
averages to daily before requesting the next.

The stress fields cover ~61% of grid cells and the missing 39% is a **fixed
spatial mask**, not scattered gaps — every cell is either always present or
always absent, never partial. Daily averaging does not and cannot repair it.
The 10 m wind fields are fully populated, so rows without stress still carry
wind speed, and the `data_quality` column records the difference.

Three things are load-bearing:

1. **`arco-time-series`, never `arco-geo-series`.** The access pattern is
   "bounded area, many timesteps". `arco-geo-series` stores one timestep per
   huge lat/lon chunk and would fetch the globe once per day of the range.
   Same reasoning as `backend/services/download/providers/copernicus.py`.
2. **The depth bound must be server-side.** These reanalysis products carry
   50 depth levels and only the surface is used. With
   `minimum_depth`/`maximum_depth` a request takes ~63 s; without it, the
   identical request did not complete in 15 minutes. This differs from the
   backend's NRT products, which have a singleton depth dim where a
   post-hoc `isel(depth=0)` is harmless.
3. **Hourly products must be downsampled inside the fetch loop**, not after
   it, or peak memory scales with the whole window instead of one chunk.

---

## Results

Real numbers from the runs in this repo — not targets. Reproduce with the
commands above; artifacts land in `reports/`.

### Problem B — fish habitat, spatial block CV

Mean over 5 spatial folds, 3° blocks:

| model | ROC-AUC | PR-AUC | TSS | Boyce |
|---|---|---|---|---|
| LightGBM | 0.959 | 0.896 | **0.826** | 0.892 |
| Random Forest | 0.953 | 0.888 | 0.821 | 0.955 |
| MaxEnt | 0.861 | 0.672 | 0.619 | 0.944 |

Held-out spatial block (885 points, 167 presences):

| model | ROC-AUC | PR-AUC | TSS | Boyce |
|---|---|---|---|---|
| LightGBM | 0.946 | 0.816 | 0.788 | 0.895 |
| Random Forest | 0.927 | 0.741 | 0.774 | 0.927 |
| Ensemble | 0.917 | 0.752 | 0.694 | 0.936 |
| MaxEnt | 0.722 | 0.365 | 0.365 | 0.884 |

> **These supersede an earlier, much lower set (CV TSS 0.66, holdout 0.53).**
> Those came from a model with **no species-dependent input at all**:
> `feature_columns()` inspected the frame before `apply_thermal_niche` had
> added the thermal columns, and `species_key` sat in the excluded-identifier
> set — so the carefully per-fold-fitted thermal niche was computed and then
> thrown away. Five "species" were one pooled model wearing five labels.
>
> Found by checking whether the exported per-species map tiles actually
> differed. They were byte-identical. `features.THERMAL_FEATURES` and
> `SPECIES_FEATURE` now name those columns explicitly, so the feature list
> cannot depend on the order two functions happen to be called in.

9% of held-out points are environmentally extrapolating (MESS < 0).

**The CV-to-holdout drop (TSS 0.67 → 0.53) is the point, not a defect.** It is
the gap between interpolating among neighbouring records and generalising to
water the model has never seen. A random K-fold split would have hidden it
and reported the higher number.

One honest caveat: `depth` and `distance_to_coast` dominate the SHAP ranking.
Target-group background sampling corrects horizontal sampling bias well, but
the background pool still skews shallower and more coastal than the pelagic
tunas that make up most presences, so some of that signal is residual
sampling geometry rather than pure habitat preference. Constraining background
draws to match the presence depth distribution is the natural next step.

### Problem A — HAB early warning

Held-out final period (2021, 577,608 grid-cell-days, 7.3–7.6% bloom rate).
The calibrated model against the persistence baseline:

| horizon | PR-AUC | persistence | ROC-AUC | TSS | Brier (raw → calibrated) |
|---|---|---|---|---|---|
| t+3 | **0.661** | 0.511 | 0.942 | 0.751 | 0.056 → **0.038** |
| t+5 | **0.493** | 0.384 | 0.884 | 0.635 | 0.073 → **0.049** |
| t+7 | **0.362** | 0.309 | 0.841 | 0.564 | 0.085 → **0.057** |

Rolling-origin CV agrees at every horizon (t+7: 0.363 vs 0.271).

Operating points, threshold set for 80% recall:

| horizon | precision | recall | false-alarm rate |
|---|---|---|---|
| t+3 | 0.449 | 0.807 | 0.551 |
| t+5 | 0.280 | 0.801 | 0.720 |
| t+7 | 0.202 | 0.811 | 0.798 |

Read the false-alarm column before treating t+7 as deployable: catching 80%
of blooms a week out means **four in five alerts are false**. The t+3 alert,
where roughly half of alerts are genuine, is the one that would survive
contact with a coastal agency.

#### How this compares to the first attempt, and why the old numbers were wrong

An earlier 2020–2021 run reported t+3 0.755 / t+5 0.525 / t+7 0.468 — higher
absolute numbers that were **worse models**. Two compounding problems, both
found by pushing on the result rather than accepting it:

**1. It lost to persistence at t+5 and t+7** (0.548 and 0.492). This is why
the baseline is scored on every fold rather than listed as future work.

**2. Even those figures were propped up by an evaluation artifact.** They came
from fitting on train+validation, i.e. right up to the test boundary. Moving
the validation slice out of training — necessary to have anything to
calibrate on — collapsed the model:

| training window | PR-AUC | ROC-AUC | TSS |
|---|---|---|---|
| train+val, ends Sep 2021 | 0.468 | 0.764 | 0.389 |
| train only, ends May 2021 | 0.235 | **0.531** | 0.064 |

ROC-AUC 0.53 is chance. A 3.5-month gap between the end of training and the
start of testing destroyed it. On six years the same honest gap gives **0.841**.

The lesson worth keeping: the current numbers are *lower* and far more
trustworthy. Absolute metric values are not comparable across evaluation
setups, and a rising number can mean a leakier evaluation rather than a
better model.

#### Why the window changed

The cause is interannual variability, verified rather than assumed. Monthly
mean chlorophyll tracks closely across 2020 and 2021 from January to June,
then diverges sharply through the southwest monsoon:

| month | 2020 | 2021 |
|---|---|---|
| Jul | 0.136 | 0.188 |
| Aug | 0.164 | 0.229 |
| Sep | 0.146 | 0.207 |

(mg/m³ basin mean; validation-period p99 is 2.11 vs 0.53 in training.)

So a 2020–2021 window puts exactly **one** southwest monsoon bloom season in
the training period and then tests on a substantially stronger one. The same
mechanism explains the bloom rate climbing 10.4% → 16.5% → 21.2% across
train/validation/test: thresholds are fitted on the training years (correctly,
to avoid leakage) and later years simply run greener.

This is the doc's own risk-table entry — "regime shift / model drift
(ENSO, Indian Ocean Dipole)" — showing up as the dominant effect rather than
a footnote. It also reorders the doc's improvement list: **more years beats
more features**, because no covariate helps a model that has never seen the
regime it is being asked about. `HAB_START` is therefore 2016.

Extending the window fixed the label drift outright:

| period | 2020–2021 window | 2016–2021 window |
|---|---|---|
| train | 0.104 | 0.102 |
| validation | 0.165 | 0.094 |
| test | 0.212 | 0.076 |

(bloom rate at t+7). The two-year split doubled across periods; the six-year
split is flat. That is what moved t+7 from chance to ROC-AUC 0.841.

#### Calibration

`class_weight="balanced"` deliberately distorts the decision boundary to keep
the minority class learnable, and the side effect is systematic
overconfidence — the raw model's 0.9–1.0 bin fires on 57% of occasions.
Isotonic regression fitted on the validation slice (never on training, where
the model is near-perfect, nor on test) corrects it: Brier improves 25–33% at
every horizon while ROC-AUC is unchanged to three decimals, exactly as a
monotonic transform must behave.

#### What the model actually uses

Share of total |SHAP| at t+7: **chlorophyll and its derivatives 36.8%, wind
34 features 14.4%**. Wind is a real but secondary contributor, and the
highest-ranked wind features are the *30-day rolling* upwelling statistics
(`upwelling_index_roll30_std`, `_roll30_mean`) rather than instantaneous
values — sustained upwelling over weeks drives nutrient supply, not any one
windy day. That is the physically expected shape, which is mild evidence the
feature is doing what it claims.

#### Label caveat that still stands

The weak-label bloom rate is ~9.7% in training, not the "low single digits"
the doc anticipates. That is a property of the labelling rule, not the ocean:
a 90th-percentile per-cell-per-season threshold yields ~10% positives by
construction. Verified in-situ blooms would be far rarer, and the imbalance
strategy would need revisiting with them.

Full per-fold scores, calibration curves and SHAP rankings are in
`reports/hab_early_warning_*.csv` and `_summary.json`.

---

## Design decisions worth knowing

**Leakage prevention is structural, not procedural.** Every fit-then-apply
pair is split into two functions (`fit_climatology`/`apply_climatology`,
`fit_bloom_thresholds`/`apply_bloom_thresholds`,
`fit_thermal_niche`/`apply_thermal_niche`) so that fitting on the wrong rows
requires actively passing the wrong frame. Rolling windows are trailing and
shifted by one step; lags shift backwards on dates, not row positions. The
only forward shift in the codebase is the target construction in
`hab_early_warning/src/labels.py`, isolated there so it is easy to audit.

**Latitude and longitude are excluded from habitat model inputs.** With
spatially clustered presences, a tree model memorises coordinates and scores
beautifully under random CV while learning no ecology. Spatial structure
enters through environment and bathymetry instead.

**Pseudo-absences come from the target group, never random ocean points.**
Marine occurrence records cluster near research institutes, ports and
shipping lanes. Random background teaches the model to separate sampled water
from unsampled water. Drawing background from other ray-finned fish records —
same surveys, same places — cancels most of that bias.

**MaxEnt is implemented as L1-regularised logistic regression** with quadratic
and hinge feature expansion. That is MaxEnt's estimator, not a substitute:
Phillips & Dudík (2008) showed the equivalence, and Renner & Warton (2013)
tied both to an inhomogeneous Poisson point process.

**HAB is framed forecast-then-threshold.** The model predicts chlorophyll
forward and a bloom is declared against a locally- and seasonally-calibrated
percentile. The threshold can be retuned per region or agency risk appetite
without retraining, and the output is an explainable trajectory rather than an
opaque label.

**The persistence baseline is scored on every fold.** "Blooming now, so
blooming in three days" is a strong forecast for an autocorrelated field. Any
model that cannot beat it has demonstrated nothing.

---

## What is deliberately not here

- **Tier 3 spatio-temporal deep models** (ConvLSTM / 3D-CNN / ViT patch
  encoder, TFT/LSTM sequence models). The doc's own risk table says to ship
  Tier 1–2 first and reserve GPU-backed Tier 3 for the pilot phase once the
  pipeline and validation framework are proven. The validation harness and
  feature store they would consume are in place.
- **HAB Stage 2, harmful/toxic classification.** This needs in-situ genus and
  toxin data (HABSOS / NCCOS / HAEDAT, or INCOIS advisories). None is openly
  queryable for this coastline, so the interface carries a `label_strength`
  field and the classifier is left unimplemented rather than faked on data
  that does not exist.
- **Strong HAB labels generally.** Everything Problem A trains on is a weak
  satellite/model-chlorophyll proxy, flagged as such.
- **ERA5 winds specifically** — superseded rather than pending. The need was
  wind stress for the Bakun upwelling index; Copernicus Marine's
  `cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H` serves scatterometer-derived
  `eastward_stress`/`northward_stress` and `stress_curl` directly, reachable
  with credentials already in `backend/.env` and with no bulk-formula
  drag-coefficient assumption. ERA5 via the CDS API would add a second
  account for a strictly worse version of the same covariate. It is still the
  right source for the variables Copernicus does not carry (precipitation,
  air-sea heat flux).
- **NASA Ocean Color, Global Fishing Watch, CMFRI, GRDC.** Registered in the
  doc's source inventory; not ingested. GFW in particular is deliberately
  deferred — the doc is emphatic it must stay a covariate and external
  validation signal, never a label, and wiring it in without that guard is the
  main circularity risk in Problem B.
- **Hyperparameter tuning (Optuna).** Model settings are hand-chosen and
  conservative. Nested rolling-origin tuning is the documented next step.
