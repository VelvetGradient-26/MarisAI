# MarisAI Forecasting Engine

One framework that forecasts **any** oceanographic variable the platform
carries. Not one model implementation per variable — one pipeline, one trainer,
one inference path, and a YAML file that says which variables exist.

```
variable + point + horizon
        │
        ▼
  history adapter ──► preprocessing ──► feature engineering
        │                                       │
        │                                       ▼
        │                          one LightGBM per (variable, horizon)
        │                                       │
        ▼                                       ▼
   provenance              prediction + bootstrap interval + SHAP drivers
```

## Adding a variable

Three steps, **no Python**:

1. Confirm the variable exists and is `available: true` in
   `services/download/registry.py`. That is what supplies its history.
2. Add a block to `config/forecasting.yaml`:

   ```yaml
   turbidity:
     code: turbidity
     covariates: [chlorophyll_a, significant_wave_height]
     valid_min: 0.0
     log_transform: true
   ```

   An empty block (`turbidity: {code: turbidity}`) is valid and inherits every
   default.
3. `python scripts/train_forecasting.py --variable turbidity`

Nothing in this package branches on a variable's name. The config loader
validates every `code` and `covariate` against the download registry at import
time, so a typo or an unimplemented provider fails immediately with a message
naming it, rather than at 3am inside a training run.

## Modules

| File | Responsibility |
|---|---|
| `config.py` | Pydantic schema for `config/forecasting.yaml`; defaults inheritance |
| `history.py` | Point time series for any registry variable, via `services/download/`; disk + memory cache |
| `preprocessing.py` | Regularise the time axis, detect outliers, fill gaps without inventing them |
| `feature_engineering.py` | Lags, rolling stats, trends, calendar/cyclic, static, neighbour hooks, **the one forward shift** |
| `evaluator.py` | Rolling-origin CV, metrics, diagnostic arrays |
| `climatology.py` | The second baseline: a day-of-year climatology, fitted per location, fit and apply split |
| `uncertainty.py` | Bootstrap prediction intervals |
| `shap_explainer.py` | TreeSHAP per-prediction drivers, humanised feature names |
| `trainer.py` | The unified training pipeline; target encode/decode |
| `model_store.py` | On-disk artifacts (`model.pkl`, `metadata.json`, `metrics.json`, `feature_columns.json`) |
| `registry.py` | Resolver across config / download registry / trained artifacts |
| `predictor.py` | Inference orchestration |
| `grid_history.py` | The point path's fetch, inverted: whole globe, many timesteps, strided while lazy |
| `grid_predictor.py` | The cell loop — the same feature chain as the point path, 40,000 times |
| `progress.py` | Opt-in progress bars; only the CLI opts in |
| `api.py` | FastAPI router, thin |

## Design decisions that were measured, not assumed

These changed the engine's behaviour materially. Each was found by running the
pipeline against real data, and each is a trap worth not falling into twice.

### 1. Models regress on the *change*, not the level

A gradient-boosted tree predicts a piecewise-constant function, so it cannot
represent the identity `y(t+h) = y(t)`. On a strongly autocorrelated
geophysical series — where persistence is a genuinely hard baseline — that
structural limit is fatal. Fitting on levels scored **worse than persistence at
every horizon**, including one day ahead:

| horizon | RMSE (level) | persistence | skill |
|---|---|---|---|
| 1 | 0.831 | 0.785 | **−0.122** |
| 3 | 1.191 | 1.173 | **−0.030** |
| 7 | 1.430 | 1.341 | **−0.137** |

Fitting on the delta makes persistence the constant zero, which a tree
represents exactly, so the model starts at parity and only learns the departure.
Same features, same data, same hyperparameters:

| horizon | RMSE (delta) | persistence | skill |
|---|---|---|---|
| 1 | 0.702 | 0.785 | **+0.201** |
| 3 | 1.062 | 1.173 | **+0.181** |
| 7 | 1.246 | 1.341 | **+0.138** |

`defaults.target_mode: delta`. The `skill_score` metric exists specifically so
this class of failure cannot ship silently — if a model does not beat
persistence, the training log says `WORSE THAN PERSISTENCE`.

### 2. Outlier filtering is **off** by default

Every source behind this engine is a quality-controlled model or reanalysis
product, not a raw instrument. Run against real Copernicus SST, the Hampel
filter flagged **5–12% of a clean daily series** at every window (7–21) and
threshold (3–5σ) tried. Its local-scale assumption inverts on a smooth field:
the series tracks its own rolling median so closely that the MAD collapses
toward zero, and ordinary variation then looks extreme against it. In one
365-day series, 74 values had a local MAD of *exactly* zero purely because the
field is smooth.

Interpolating over 12% of a good SST record is the same fabrication this
platform refuses everywhere else. Turning the filter off raised 7-day skill
from +0.138 to +0.202.

The filters stay implemented and are one config line away, for sources that
genuinely need them — buoy feeds and satellite retrievals, where a spike really
is an instrument artifact.

### 3. A provider fetch needs a timeout, not just a retry

Retrying on an exception is not enough, because the failure that cost the most
here was not an error. A Copernicus zarr read simply never returned: a training
run sat on it for **98 minutes** looking perfectly healthy — process alive, no
exception pending, nothing that would ever have raised. Silence and progress
are indistinguishable without a deadline.

`history._fetch_with_retry` now bounds each attempt at 300s and retries with
backoff, per provider rather than around the whole `gather` (retrying the group
would re-issue the slow Copernicus reads to work around a fast ERDDAP blip).

The retry matters on its own too: a single transient GEBCO 503 cost 6 of 24
training points in one run — a quarter of the model's geography, including the
entire Gulf Stream and Coral Sea — for a provider supplying one constant column
that was fine again seconds later.

### 4. Every horizon must request the *same* window

`_point_features` pads its fetch window by the variable's **largest** configured
horizon, not the one being trained. Padding by the current horizon shifts the
start date each pass, which changes the cache key, which silently refetches all
24 points once per horizon. Since the fetch dominates a training run, that was
most of its cost — a 4× penalty that looked like nothing but slowness.

`test_every_horizon_of_a_variable_requests_one_shared_window` asserts on the
cache keys the trainer actually emits, so the property survives a refactor of
the arithmetic.

### 5. Rolling windows close at `t`, not `t−1`

Everything trailing is inclusive of the current step. That is safe *because*
the horizon is always ≥ 1, and `add_forecast_target` rejects 0 rather than
merely discouraging it. Closing at `t−1` instead would silently discard the
most recent observation and make every model behave like an `h+1` model.

### 6. Persistence alone is an insufficient baseline

Skill against persistence *rises* with horizon on several variables here. That
is exactly the signature of a model that has learned nothing but the seasonal
cycle — persistence error grows with horizon, a seasonal cycle's does not — so
the persistence-referenced score of such a model stays flat or improves while
the model genuinely degrades. Reporting persistence alone fails in the direction
that flatters the model.

`climatology.py` is the second baseline. Across 13 variables × 4 horizons:

| median skill | h=1 | h=3 | h=7 | h=30 |
|---|---|---|---|---|
| vs. persistence | +0.272 | +0.154 | +0.151 | **+0.273** |
| vs. climatology | +0.958 | +0.729 | +0.410 | **−0.023** |

Climatology skill declines with horizon for **13 of 13** variables. Eleven
model–horizon combinations beat persistence while losing to climatology; under a
persistence-only convention every one of them reads as a success.

Two details of the construction matter. **Fit and apply are two functions**, for
the same reason `machine_learning/` splits every such pair — a climatology
fitted over the full record leaks the evaluation period into the *baseline's*
definition, which flatters the baseline and understates the model. And the
estimate pools a **±15-day circular window** rather than taking a bare
(location, day-of-year) mean: these series are ~2.2 years long, so a bare mean
averages two samples and would be a strawman the model beats for the wrong
reason.

**The obvious conclusion from all this is wrong, and that is the finding.** An
earlier draft concluded those models had "learned what month it is." A three-arm
feature ablation showed **10 of the 11 keep their skill when every calendar
feature is removed**, while the most calendar-dependent variable in the study
(water temperature at h=30, 68% of its skill calendar-borne) comfortably *beats*
climatology. Losing to climatology reports the **baseline's** strength, not the
model's mechanism — diagnosing mechanism needs the ablation, and two baselines
cannot do it. Written up in `../../research/`.

## The shipping bar

A horizon ships only if **skill > 0 and at most 1 of 5 folds is negative**. The
second clause is the load-bearing one: six previously rejected horizons printed
`beats persistence` on the aggregate line the training log shows, because an
aggregate can read healthy over folds that include negatives.

`scripts/train_forecasting.py` has no concept of rejection — it trains every
*configured* horizon and saves each one that fits, so a batch retrain silently
resurrects horizons that were deleted on their own merits. `scripts/apply_shipping_bar.py`
re-applies the rule afterwards:

```bash
python scripts/apply_shipping_bar.py --dry-run
python scripts/apply_shipping_bar.py --variable nitrate
python scripts/apply_shipping_bar.py            # every trained variable
```

Failures are **moved** to `models/forecasting/_rejected/<YYYYMMDD>/`, never
deleted: the artifact is the evidence for the decision, and the next person to
propose retraining one should be able to read why it was dropped.

## The grid path

`grid_history.py` + `grid_predictor.py` + `scripts/build_forecast_grid.py` turn
the engine into a global raster layer (served by `services/forecast_tiles.py`).

**The grid path is the point path with the network replaced by an in-memory
slice.** `GridStack.slice_point` returns the same `{provider: (spec, Dataset)}`
shape the point path's fetch builds, and the cell loop then calls the *same*
`build_dataframe` → `clean` → `build_features` chain. There is deliberately no
grid-native feature builder: that is how train/serve skew gets in, and a
40,000-cell loop is exactly where the temptation to write one is strongest.
`tests/test_forecast_grid.py::test_grid_matches_the_point_path` compares the two
cell for cell on identical synthetic inputs (agreeing to 1e-6) and is what makes
optimising the loop safe to attempt.

Three further properties:

- **The fetch is inverted**, and `arco-geo-series` is why it is possible — whole
  globe, many timesteps, a third access pattern the downloader never had.
  Striding happens *while the array is still lazy*: a global 0.083° float64
  field is ~70 MB per timestep per variable.
- **Cost is dominated by the fetch, which does not care about output
  resolution.** `--resolution 4.0` speeds up the cell loop and nothing else.
- **The build runs in a worker thread and must keep doing so.** Everything past
  the fetch is ~15 minutes of CPU with no `await` in it, and the scheduler
  starts it on the server's event loop at boot.

Not every variable can have a grid. Open-Meteo variables are served by a point
API capped at 900 points, so they can be forecast and charted but never painted
— `grid_history.ungriddable_reason` lets the builder skip such a *target* before
paying for a fetch, and a missing *covariate* is recorded in the grid's
`missing_covariates` attribute and surfaced in the layer's attribution, because
LightGBM routes an absent feature down its missing-value branch without
complaint and the map would otherwise look exactly as confident as a complete
one.

Where two grids hold the components of one vector, `services/forecast_vectors.py`
composes them into a particle field instead of a colour ramp. **A pair is always
two forecast *components*, never a forecast bearing.** `current_direction`,
`wind_direction` and `wave_direction` are degrees on 0–360, where 359 and 1 are
neighbours, and every operation between a grid and the screen is linear —
averaging them gives 180°, the exact opposite heading. Everything *downstream*
of the model handles that (sin/cos resampling, a signed veer wrapped to ±180 for
`change` mode, a cyclic ramp whose ends are the same colour by construction),
but the modelling half is still linear: with `target_mode: delta` a 5° veer
across north trains as −355°. The answer is to predict components and derive the
angle, which is why `wind_u`/`wind_v` were configured as variables of their own
rather than deriving a field from `wind_speed` + `wind_direction`.

`circular` has exactly one home — `VariableInfo` in
`services/download/registry.py`. `VariableConfig.circular` *inherits* it, the way
label and unit already do. It was briefly declared in the YAML too, and the two
disagreeing is the failure worth designing out: the modelling half would encode
sin/cos while the renderer painted a linear ramp, and both would look plausible.

**Never quote a grid count.** `ls models/forecasting/_grids/` and
`GET /api/dashboard/data-quality` are the only trustworthy answers.

## Leakage discipline

There is **exactly one forward shift** in this package —
`feature_engineering.add_forecast_target`. Everything else is trailing by
construction. `tests/test_forecasting.py::test_only_one_forward_shift_exists_in_the_package`
scans the source and fails if a second appears, so the property stays true for
features nobody has written yet.

Validation is **never** a random split. `evaluator.rolling_origin_splits` is
chronological and expanding, with an embargo gap defaulting to the forecast
horizon — a training row within `h` steps of the test window shares its target
period, so without the gap the score measures memorisation.

## Training

```bash
cd backend

# see what would run, no network
.venv/bin/python scripts/train_forecasting.py --all --dry-run

# one variable, its configured horizons
.venv/bin/python scripts/train_forecasting.py --variable sea_surface_temperature

# specific horizons, with diagnostic PNGs
.venv/bin/python scripts/train_forecasting.py -v chlorophyll_a --horizons 1 7 --plots

# everything (long — one upstream fetch per point per variable)
.venv/bin/python scripts/train_forecasting.py --all --skip-existing
```

Training is offline and **never** triggered by the API. A forecast request must
not be able to start a job that fetches two years of data from 24 points.

A model is **global**: one LightGBM per (variable, horizon) fitted across all
configured points at once, with latitude, longitude, ocean depth and basin as
features. That is what lets it score an arbitrary coordinate a user clicks on
rather than only the points it saw.

## Artifacts

```
models/forecasting/<variable>/h<horizon>/
    model.pkl              pickled LightGBM regressor
    metadata.json          version, training window, points, params,
                           target_mode, residual quantiles, duration
    metrics.json           rolling-origin CV metrics, per-fold scores,
                           diagnostics arrays, SHAP importance, baseline
    feature_columns.json   exact column order the booster was fitted on
```

The horizon subdirectory is the one departure from a flat `models/sst/` layout:
this engine trains a separate model per horizon (direct, not recursive), so a
1-day and a 30-day model coexist.

`feature_columns.json` is separate from `metadata.json` because the predictor
reads it on the hot path to reindex the inference row into the trained column
order. Column order silently mattering is a classic way a served model diverges
from the validated one.

## API

`POST /api/v1/forecast`

```json
{
  "variable": "sea_surface_temperature",
  "latitude": 12.5,
  "longitude": 74.0,
  "forecast_horizon": 7,
  "history_window": 90
}
```

```json
{
  "prediction": 28.34,
  "confidence_interval": {
    "lower": 25.81, "upper": 31.01,
    "confidence_level": 0.95,
    "method": "residual_bootstrap", "n_residuals": 1370
  },
  "trend": "Stable",
  "top_features": [
    {"feature": "air_temperature", "label": "Air Temperature",
     "value": 28.43, "contribution": 0.31, "direction": "increases"}
  ],
  "model": "LightGBM",
  "evaluation": {"MAE": 0.86, "RMSE": 1.25, "R2": 0.91, "skill_score": 0.14},
  "history": [{"t": "2026-07-06T00:00:00", "v": 29.33}],
  "data_quality": {"rows": 66, "filled": {}, "unfilled": {}},
  "sources": ["Copernicus Marine Service (...)", "Open-Meteo (...)"]
}
```

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/forecast` | One variable, one point, one horizon |
| `POST /api/v1/forecast/batch` | Several horizons at one point (forecast curve) |
| `GET /api/v1/forecast/catalog` | What can be forecast, what is trained |
| `GET /api/v1/forecast/models` | Registry contents with headline metrics |
| `GET /api/v1/forecast/models/{variable}/{horizon}` | Full metrics, SHAP importance, diagnostics |
| `GET /api/v1/forecast/variables/{variable}` | One variable's forecasting config |

Status codes follow the dashboard's rule: an **untrained model is a 404 that
tells you how to train it**, not a 500. A configured-but-untrained variable is
listed in the catalog with `available: false` and a reason, so the UI can grey
it out instead of offering a forecast that fails.

Diagnostics are served as **JSON arrays, not images**, so the dashboard renders
them in the viewer's theme. `--plots` writes PNGs from the same data for the
offline report.

## Uncertainty

`residual_bootstrap` (default) resamples the model's **out-of-sample** residuals
from rolling-origin CV. The interval is therefore calibrated against error the
model actually made on data it had not seen, at that horizon. Quantiles are
computed once at training time and stored in metadata, so inference adds two
floats rather than 500 resamples.

Residuals are `predicted − actual`, so recovering the actual means *subtracting*
them: the upper residual quantile maps to the interval's **lower** bound.
Getting that backwards yields an interval correct in width and inverted in skew
— nearly invisible on a symmetric distribution, quite wrong on chlorophyll.

`bagged_bootstrap` is also available. It captures *model* uncertainty but not
irreducible noise, so it is systematically narrower and must not be read as a
forecast interval on its own.

## Not implemented, deliberately

- **Neighbour features** — `NeighbourFeatureProvider` Protocol and the call
  site exist; the history adapter serves a single point, so there is no
  neighbourhood to average. Implementing it is one class plus a config key.
- **Distance to coast** — needs a coastline geometry or distance raster the
  backend does not carry. `distance_to_coast_km` returns `None` and the column
  is *omitted*, rather than filled with a placeholder SHAP would happily rank.
- **ConvLSTM / Temporal Fusion Transformer** — hooks only. `trainer.build_model`
  dispatches on `config.kind`; adding one is a branch there and nowhere else,
  since the rest of the pipeline needs only `fit`/`predict`.
- **Prophet** — benchmark only, never saved, never served. Off by default
  (heavy optional dependency). `enabled: true` in the baseline config plus
  `uv add prophet` turns it on; if it is missing, `metrics.json` records
  `available: false` with the reason rather than failing the run.

## Relationship to `machine_learning/`

`machine_learning/` is offline and stays out of the backend's import graph;
`services/predictions.py` serves its **precomputed grids** without loading a
model. That boundary is unchanged.

This engine is different in kind. It answers an arbitrary
(variable, point, horizon) that no offline export could enumerate, so it runs
inference in-process — which is why the backend now carries LightGBM and SHAP.
It does not import `machine_learning`, and `machine_learning` does not import
it; the leakage and validation conventions are deliberately mirrored between
them rather than shared.
