# TODO

Jobs identified during the 2026-08-05 review. Ordered within each section by
what unblocks the most other work, not by size.

Numbers here were measured, not estimated — where a figure appears, it came
from an actual run against this repo. Re-verify before relying on any of them
if it has been a while.

---

## 1. ~~MLflow experiment tracking~~ — done 2026-08-05

`machine_learning/marine_ml/tracking.py`, with all three producers tracked and
110 existing runs backfilled. Browse with:

```bash
cd machine_learning && uvx --from mlflow mlflow ui --backend-store-uri sqlite:///mlruns.db
```

| producer | how | experiment |
|---|---|---|
| `fish_habitat_prediction` | logs on `save()` | `fish_habitat_prediction` |
| `hab_early_warning` | logs on `save()`, one run per horizon | `hab_early_warning` |
| backend forecasting engine | JSON -> `marine_ml.ingest_forecasting` | `forecasting_engine` |

Decisions that are load-bearing, not incidental:

- **The backend dependency is inverted, not added.** `backend/` writes plain
  stdlib JSON (an immutable `_reports/runs/<timestamp>/` per invocation) and
  the ML side *reads* it. The backend never learns tracking exists, so the
  import boundary holds. `tests/test_training_run_record.py` asserts the
  `mlflow` import never appears in `backend/` — the natural "improvement"
  someone makes later is to log directly from the training script, and that is
  precisely what must not happen.
- **`mlflow-skinny`, not `mlflow`.** The full package pins `pandas<3` and
  `pyarrow<23`, so installing it downgrades the ML env from pandas 3.0.5 /
  pyarrow 25 — a major-version pandas downgrade underneath a 3.9M-row parquet
  feature store. Skinny + SQLAlchemy is the same client with none of that; the
  UI runs via `uvx` and never enters the venv. **Do not "simplify" this to
  plain `mlflow`.**
- **Fold spread is logged, not just the mean.** `passes_bar` encodes the
  shipping rule as a metric — overall skill > 0 **and** ≤1 of 5 folds negative.
  Backfilling all 109 shipped forecasting models scored `passes_bar = 1` for
  every one, independently confirming the manual curation.
- **Tracking never fails a training run.** A HAB run is ~40 min; losing it to a
  locked store would be worse than not tracking. Every path degrades to a
  warning; `MARINE_ML_TRACKING=0` opts out.
- **Ingestion is idempotent**, keyed by `(variable, horizon, trained_at)`, so a
  retrain appends a new run instead of replacing the old one. Verified by
  retraining `ph` h7: two runs, both preserved, identical skill.

Still worth doing later: nothing blocks modelling work now, but the two ML
pipelines log a *single* run per invocation for habitat and one per horizon for
HAB — if per-model-member tracking is ever wanted for the habitat ensemble,
that is the natural extension.

## 2. ~~Train more `forecasting.yaml` variables~~ — 31 of 32 done, 1 rejected

`backend/forecasting/config/forecasting.yaml` configures **32 variables**;
`backend/models/forecasting/` now contains **31** (115 models), up from 2.
Trained 2026-08-05 across 24 global points (~3 h wall clock), with `rainfall`
and `sea_level_anomaly` completed 2026-08-06 once the Open-Meteo quota reset.
The one remaining variable, `sea_surface_salinity`, is untrained deliberately
rather than pending — see the rejection list below.

| family | variables | skill range (h1 -> h30) |
|---|---|---|
| waves | significant/maximum wave height, mean/peak wave period, wave_direction | +0.08 -> +0.43 |
| atmospheric | wind_speed, wind_gust, wind_direction, pressure, humidity, air_temperature, rainfall | +0.12 -> +0.49 |
| currents | current_u, current_v, current_speed, current_direction | +0.06 -> +0.41 |
| biogeochemistry | chlorophyll_a, dissolved_oxygen, ph, nitrate, phosphate, silicate, primary_productivity | +0.03 -> +0.53 |
| optics | diffuse_attenuation, water_clarity | +0.03 -> +0.35 |
| physical | sea_surface_temperature, sea_surface_height, water_temperature, bottom_temperature, water_salinity, sea_level_anomaly | -0.06 -> +0.44 |

**Skill rises with horizon on nearly every variable** — persistence decays fast
on dynamic fields while the model holds. That is the signature of a forecast
doing real work, not echoing the last value. The exceptions are diagnostic: the
variables where skill *falls* with horizon (salinity, bottom temperature) are
exactly the ones whose targets barely move, where persistence is unbeatable.
`chlorophyll_a` h1 is the strongest result in the repo (+0.529, a 31% error
reduction on persistence) for the mirror-image reason — chlorophyll is patchy
and advected, so persistence is a weak baseline with real headroom.

### The bar applied, and why the headline is not enough

A horizon ships only if **overall skill > 0 AND at most 1 of 5 folds is
negative**. The second clause is load-bearing: the training log prints only the
aggregate, and *six* of the rejected horizons below print `beats persistence`
on it. Every shipped horizon was re-read from its `metrics.json` folds.

Rejections, all deliberate — do not blindly retrain these expecting better:

- **`sea_surface_salinity` — dropped entirely.** h3 -0.152, h7 -0.118; the
  passing horizons were inside fold noise. See the note above its YAML block.
- **`water_salinity` h3/h7 deleted, h1+h30 kept.** Same physics as above
  (h3 -0.065 with 3/5 folds negative, h7 -0.029 with 4/5). **Kept where
  `sea_surface_salinity` was dropped** because its h1 is materially better:
  +0.179 with 0/5 folds negative and tightly clustered (+0.110..+0.225),
  against surface salinity's noisy +0.085. The decision differs because the
  evidence differs, not by oversight.
- **`bottom_temperature` h1 only.** h3 -0.056, h7 -0.060, h30 -0.025 (4/5
  folds negative). h1 is +0.241 and clean. "Forecastable a day out, not
  beyond" is the honest claim.
- **`humidity` h1 deleted.** -0.020 with 2/5 folds negative (one at -0.435).
- **`nitrate` h3 deleted.** +0.050 on the mean but folds span -0.123..+0.208,
  two negative — the mean is carried by a minority of folds.
- **`sea_level_anomaly` h7/h30 deleted** (2026-08-06). Both printed
  `beats persistence` — +0.073 and +0.111 — and both had **2 of 5 folds
  negative** (h7 spans -0.296..+0.222, h30 -0.091..+0.379). This is the
  cleanest demonstration in the repo of why the second clause exists: the
  training log alone would have shipped them. h1 (+0.367) and h3 (+0.394) are
  kept, both 0/5 negative and tightly clustered.

Weakest thing kept: `diffuse_attenuation` h3 at +0.026 (1/5 negative). Revisit
it first if the bar is ever tightened.

### ~~Remaining (2), both blocked on quota rather than skill~~ — retrained 2026-08-06

Both were blocked on **Open-Meteo**, whose free tier was exhausted mid-run on
2026-08-05: **training the full variable set in one day exceeds the daily
quota** — four Open-Meteo variables trained fine, rainfall was the fifth and
tipped it over, escalating minutely -> hourly -> daily limits. A day later the
quota had reset and both trained. Spread the Open-Meteo variables across days,
or use a paid key.

**`rainfall` — all four horizons shipped.** Skill rises with horizon, the
signature of a real forecast:

| horizon | skill | folds negative | points | southern points |
|---|---|---|---|---|
| h1 | +0.334 | 0/5 | 21/24 | 4/6 |
| h3 | +0.421 | 0/5 | 20/24 | 4/6 |
| h7 | +0.428 | 0/5 | 21/24 | 4/6 |
| h30 | +0.475 | 0/5 | 21/24 | 4/6 |

**`sea_level_anomaly` — h1 and h3 shipped, h7 and h30 trained and deleted.**
h1 +0.367 and h3 +0.394, both 0/5 folds negative and tightly clustered. h7
(+0.073) and h30 (+0.111) both printed `beats persistence` with **2 of 5 folds
negative** — see the rejection list above; they are the cleanest case in the
repo for why the aggregate alone is not the bar.

That leaves **31 of 32 variables trained (115 models)**. The only untrained
one is `sea_surface_salinity`, deliberately — see the note in its YAML block.

Two things about the failures worth keeping, because they are not equally safe:

- `sea_level_anomaly` failed *loudly* on 2026-08-05 (all 24 points gone ->
  hard error, nothing written), while `rainfall` **degraded silently** — enough
  points survived to train, but only 10 of 24 and every one
  northern-hemisphere, with a different subset per horizon. Those models were
  deleted rather than shipped: a global model carrying lat/lon as features and
  no southern data would extrapolate across the equator on the one variable
  whose seasonality inverts. **Partial success is the more dangerous failure
  mode.** Check `skipped_points` in the artifact metadata, which records it
  faithfully — it is what made the retrain reviewable at all.
- **The retrain is only shippable because the coverage came back, not because
  the skill did.** 429s still cost 3-4 points per horizon, but every horizon
  retains four of the six southern points, so the equator-extrapolation
  objection no longer applies. Rainfall's first h1 pass kept only 14 of 24
  points; it was retrained on its own (~50 s, since the covariate history was
  cached by then) to get to 21. Apply the same check to any Open-Meteo variable
  trained under a hot quota: skill and folds can look perfect on a model that
  has lost a third of the planet.

### If a variable is ever added to the YAML

The configured set is now exhausted, so what remains here is the procedure for
a *new* variable. It stays the highest AI-surface-per-unit-effort item in the
repo: one YAML block naming a code the download registry already serves, plus a
training run, yields a complete metric-intelligence page at
`/dashboard/<variable>` with **no frontend edit** (verified: `/dashboard/nitrate`
renders fully and correctly omits the sections it has no capability for).

- Watch the `skill_score` line in the training log. `WORSE THAN PERSISTENCE`
  means do not ship that variable+horizon, not "tune it a bit" — and a
  `beats persistence` is not sufficient either, since it is the aggregate.
  Read the folds.
- Check `skipped_points` before shipping, not just the metrics.
- Not every variable will train well; a variable that cannot beat persistence
  should stay untrained rather than ship a page that implies a working
  forecast.

## 3. Global forecasting

Both ML models are regional — `ARABIAN_SEA` (HAB) and `NORTH_INDIAN_OCEAN`
(habitat) — while the map, dashboard and downloader are global. The forecast
grid path is already global, so this is mostly about the two `machine_learning/`
problems and about grid build cost.

- Cost is dominated by the fetch and is **independent of output resolution**:
  ~1080 whole-globe reads (~35 min) plus ~15 min of cell loop at 1°.
  `--resolution 4.0` speeds up only the loop.
- The ~40x cheaper daily Copernicus products were measured and deliberately not
  adopted: they would collapse hourly wind onto a daily axis inside
  `build_dataframe`'s inner join, turning wind speed from a 24-hour mean into
  one instantaneous value. Solve that before swapping them in.
- Open-Meteo variables can never be gridded (point API, 900-point cap).
  `grid_history.ungriddable_reason` already encodes this — extend rather than
  work around it.
- Region expansion for HAB/habitat is bounded by data, not code: the habitat
  window is 2000–2013 because OBIS target-species records stop after 2014.

---

## 4. Conversational agent over the existing API (in progress)

Not RAG — **tool-calling** over the ~40 endpoints that already exist. "What is
the 7-day SST forecast off Kochi, and how does it compare to last year?" becomes
calls to `/api/v1/forecast` and `/trends`, narrated over the real returned
numbers. Grounded in live data, and it surfaces the whole platform through one
interface.

- ~~The gap is that `generate(prompt) -> str` has **no tool-calling**.~~
  **Stale as of 2026-08-05 — this is built.** `services/chat/` has a
  tool-calling agent over **9 tools** (`tools.py::_SPECS`:
  `list_available_variables`, `get_point_forecast`, `get_current_conditions`,
  `get_seafloor_depth`, `get_global_ocean_summary`, `get_active_alerts`,
  `get_historical_series`, `get_fishing_habitat`, `get_bloom_risk`), a
  per-conversation `Ledger`, and a grounding check (`agent._ungrounded_numbers`)
  that rejects any figure no tool returned. `services/llm.py`'s
  provider-agnostic `LLMProvider` Protocol (Gemini / OpenAI / Ollama) is still
  the config surface. Tool count is within the 5–8 guidance below, at 9.
- Reuse `services/metrics/story.py`'s discipline: compute first, phrase second,
  and verify that every number in the response is derivable from the facts
  block. Hallucinated ocean readings are the whole risk here, and that pattern
  is the existing mitigation.
- Keep the agent's tool surface narrow (5-8 tools). Every tool is a prompt the
  model can get wrong.

## 5. ConvLSTM / U-Net for spatial forecasting

**The argument for deep learning here is architectural, not decorative.**
`grid_predictor` scores every cell **independently** — it loops cell by cell
through the point pipeline, deliberately, to avoid train/serve skew. The
consequence is that the model cannot see spatial structure at all: not an eddy,
not a front, not the shape of a bloom. A gradient-boosted tree over per-cell
features is structurally blind to the neighbourhood.

That is a real gap a convolutional/recurrent model fills, and it is defensible
under questioning in a way that bolting an LSTM onto tabular data is not.

- Baseline to beat is strong and already measured: delta-target LightGBM at
  skill +0.20 vs persistence. **Trees beating neural nets on tabular data is
  the norm** — the claim to make is "DL where trees are provably blind
  (fields), trees where they win (points)", not "DL is better".
- Two candidate framings, smaller first:
  - **U-Net segmentation of HAB bloom extent** over chlorophyll fields.
    Contained, and 3.9M labelled rows already exist.
  - **ConvLSTM over SST/chlorophyll fields** for grid-to-grid forecasting.
    Directly extends the forecast map.
- Cost: the gridded training data is the expensive part (~35 min per fetch
  window, resolution-independent). Budget for that before any modelling.
- Do not start this until (1) MLflow exists — otherwise "did it help?" is
  unanswerable — and (4) works.

## 6. RAG — scope carefully, most framings do not typecheck

RAG retrieves from unstructured text. MarisAI's data is numeric grids and time
series; you do not *retrieve* SST, you query it. "RAG over ocean data" is a
category mismatch and should not be built.

Two targets are legitimate:

- **The data catalog itself** — 36 variables x provider, dataset, grid spacing,
  cadence, coverage start, citation, licence. Genuinely useful ("which
  variables cover 2015 daily at 0.083 degrees?"). But this is ~36 records: it
  **fits in a single prompt**. Prompt-stuffing is the correct implementation.
  Standing up a vector database for 36 documents is the trap to avoid.
- **Scientific literature** on HABs and the five target species. This is real
  RAG with a real corpus, and would genuinely deepen the explainability
  sections — but it is a separate ingestion project that does not touch the
  platform's own data path. Treat it as its own effort, not as a feature of
  the chatbot.

Sequence: do the catalog version as prompt context inside (4) first, and only
consider a vector store if the literature corpus is actually pursued.

---

## Bugs and correctness

### ~~Provider field-name collision crashed every surface+depth request~~ (fixed 2026-08-05)

`cleaning.py::_merge_provider_datasets` merged raw provider Datasets before
renaming them to registry codes. An upstream field name is unique only *within*
a product: Copernicus serves `thetao` as surface temperature in the physics
product and as a depth-resolved profile in `..._thetao_depth`, and `so`
likewise for salinity. `xr.merge` saw one name with two value sets and raised
`MergeError: conflicting values for variable 'thetao'`.

Wider than it looks — the same path serves all three consumers, so this broke
the **downloader** (selecting water temperature + SST together returned a 500 —
a legal, obvious pairing), the **forecasting engine** (`water_temperature`'s
configured covariate *is* `sea_surface_temperature`, so it could never train),
and any **gridded build** of either variable.

Fixed by namespacing data variables per provider (`copernicus_physics::thetao`)
before the merge, so the collision is structurally impossible rather than
depending on no two providers ever choosing the same name. Both halves needed
it: derivations name raw fields too, and `current_speed` (hypot of `uo`/`vo`)
would have thrown `KeyError` if only the `source_field` lookup were qualified.
`tests/test_download_field_collisions.py` pins it, including a registry guard
that fails if a *third* collision ever appears.

### Fish-habitat ensemble scores below its own best member

`fish_habitat_prediction` weights ensemble members by **normalized CV TSS**,
which compresses a large quality gap into a small weight gap:

| model | CV TSS | weight | holdout TSS |
|---|---|---|---|
| lightgbm | 0.826 | 0.364 | **0.788** |
| random_forest | 0.821 | 0.362 | 0.774 |
| maxent | 0.619 | **0.273** | 0.365 |
| ensemble | — | — | **0.694** |

MaxEnt gets 27% of the vote at less than half the holdout TSS, and the exported
product (`habitat_suitability.nc`) is the ensemble. **Not a pure loss:** the
ensemble has the best Boyce index (0.936 vs 0.895), so it is better spatially
calibrated while being worse at discrimination. The problem is that this
tradeoff is currently made implicitly by a weighting formula. Make it
deliberate: drop MaxEnt, weight by rank/softmax rather than raw TSS, or stack
on out-of-fold predictions.

### ~~`machine_learning/` tests do not run~~ (fixed 2026-08-05)

`pytest tests/` failed at collection with `ModuleNotFoundError: No module named
'marine_ml'` — there was no `pyproject.toml`, `pytest.ini` or `setup.cfg` in
`machine_learning/`.

Higher risk than a normal broken path because of *what* those tests are: they
enforce "only one forward shift exists", "never random K-fold", and
"climatology fitted on training rows only". They are the guardrails against
silent methodology error, and they were invisible to anyone running pytest the
obvious way.

Fixed by `machine_learning/pytest.ini` (`pythonpath = .`, `testpaths = tests`).
A bare `pytest` now collects and passes all 45.

### ~~Feature store is stored at float64~~ (fixed 2026-08-06)

`data/processed/feature_store/hab_gridded.parquet` was 3.9M rows x 151 columns,
2.80 GB, with **142 `double` columns** — it predated `compact_dtypes` being
wired into `write_feature_store`. `read_feature_store` compensated, but only
*after* `pd.read_parquet` had materialized the full-width table, so peak was
~7 GB with both copies alive: the OOM-with-no-traceback its own docstring warns
about, paid on every experiment iteration.

Both halves done, measured on the real store:

| | before | after |
|---|---|---|
| file on disk | 2.80 GB | **1.59 GB** |
| full read | — | 3.5 s, 2.82 GB peak RSS |
| 20-of-151-column read | 3.5 s / 2.82 GB | **0.1 s / 1.08 GB** |

- `scripts/compact_feature_store.py <name>` rewrites a store at the dtypes
  `compact_dtypes` would give it. It streams row group by row group and casts
  with **Arrow, not pandas** — loading 3.9M x 151 float64 to cast it would need
  the exact peak this removes. Writes a sibling file and renames only after row
  counts and column names match, so an interrupted run is a no-op.
- `read_feature_store(name, columns=[...])` pushes projection into Parquet, and
  `feature_store_columns(name)` reads the schema from the footer without
  touching a row group. `tests/test_feature_store.py` asserts on what Parquet
  was *asked* for, not just on the returned frame — selecting after
  `read_parquet` returns an identical frame while paying the full cost, so a
  frame-only test would pass against the useless implementation.
- Still true, and still the reason not to migrate: do **not** move this to
  Postgres/Mongo/Redis. Row stores read all 151 columns to serve 12; Parquet
  reads 12. If it outgrows one machine, DuckDB reads these same files in place
  with no import step.

### HAB t+7 sits at the edge of usefulness

At the 0.8-recall operating point: precision 0.202, false-alarm rate 0.798 —
four of every five alerts are false. Defensible for a screening tool where a
miss costs more than a false alarm, but that should be an explicit decision
recorded in the UI copy, not a horizon that merely exists.

### Small habitat holdout

885 rows / 167 positives. The confidence interval on holdout TSS 0.788 is wide;
the spatial folds (471–791 rows each, TSS 0.76–0.90) are the more trustworthy
signal. Report both rather than the holdout alone.

---

## Documentation drift

- ~~CLAUDE.md states "the HAB window is 2 years"~~ — corrected 2026-08-05.
  `marine_ml/config.py` has `HAB_START = 2016-01-01`, `HAB_END = 2021-12-31`
  (six years) and `fusion.py`'s docstring agreed ("6-year daily feature
  table"); CLAUDE.md now says six years, and records that it is *region*, not
  span, that was traded away for daily fields.

---

## Deferred / considered and rejected

- **A database for caching.** Every in-process cache is already bounded with
  eviction; the on-disk fetch cache is 4.6 MB. Memory was concentrated in a few
  global float64 arrays, addressed directly (SST cache: ~140 MB -> ~35 MB via
  float32 plus removing a duplicated array). Redis/Mongo would relocate those
  bytes while adding a second resident copy plus serialization on the hot path.
- **A database for the ML feature store.** Parquet is the correct technology for
  wide float matrices; see the feature-store item above.
- **Postgres for persistence** remains genuinely open, but for *records* rather
  than cache or features: download history/audit, feedback (currently
  `feedback_log.jsonl`), and the KPI ring buffer that does not survive restart.
