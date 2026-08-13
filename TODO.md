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
- ~~The ~40x cheaper daily Copernicus products would collapse hourly wind onto
  a daily axis inside `build_dataframe`'s inner join. Solve that before
  swapping them in.~~ **The join half is fixed (2026-08-10); the ~40x is not
  confirmed.** See "Mixed-cadence merge" below.
- **26 of the 31 trained variables are griddable and only 3 grids exist**
  (`bottom_temperature`, `chlorophyll_a`, `current_direction`). The other five
  are Open-Meteo and can never be gridded. So the forecast *map* is where
  "global" is actually missing — 23 variables are trained, served at any point
  by `POST /api/v1/forecast`, and invisible as a layer. That is a long run
  rather than an engineering problem, and it gets cheaper if the daily-product
  question below resolves in its favour.
- Open-Meteo variables can never be gridded (point API, 900-point cap).
  `grid_history.ungriddable_reason` already encodes this — extend rather than
  work around it.
- **Re-measure the daily products through the real fetch path before adopting
  them.** Probed 2026-08-10 by reading one global surface field strided to 1°:
  hourly physics **34–46 s/timestep**, daily thetao **84–104 s/timestep** — the
  daily product is ~2.5x *slower per read*, because those datasets carry 50
  depth levels and a geo-series chunk brings the whole depth column down for a
  surface field. 45 × ~98 s still beats 1080 × ~39 s by a lot on paper, but
  this probe read the lazy array directly rather than going through
  `copernicus.fetch_global`, and neither figure reconciles with the ~35 min a
  real SST grid takes. Redo it through the real path **with a server-side depth
  bound** (`minimum_depth`/`maximum_depth`) — that is the same omission
  `machine_learning/` documents turning a 15-minute-plus fetch into ~60 s, and
  it may be the entire discrepancy. The 1.05 s/0.60 s per-timestep figures
  previously recorded in `grid_history.py` were not measured through this path
  and should not be trusted.
- Note the *merged* daily product `cmems_mod_glo_phy_anfc_0.083deg_P1D-m` is
  **not** the substitute — it carries `zos`/`tob`/`sob`/`mlotst` and sea ice but
  not `thetao`/`so`/`uo`/`vo`. The per-variable daily datasets
  (`...phy-thetao...`, `...phy-so...`, `...phy-cur...`, all 50-level) are.
- ~~Region expansion for HAB/habitat is bounded by data, not code~~ — **the
  code side is now built (2026-08-10)**; see below.

### Global PFZ and multi-region HAB — built 2026-08-10

Both `machine_learning/` pipelines now take `--region`. The default region keeps
its historic artifact names, so the regional models remain untouched as the
baselines a wider model has to beat. Everything a global extent needs is opt-in
for the same reason.

What actually broke at planetary scale, and what it cost to fix — all measured:

| | before | after |
|---|---|---|
| Copernicus service, global monthly, 1 year | 89.0 s (`arco-time-series`) | **7.5 s** (`arco-geo-series`) |
| Global physics window, in memory | ~35 GB in one array | **135 MB/year**, lazy, chunked |
| Global bathymetry | 233M cells — ERDDAP refuses | **5.1 s / 7.9 MB** at stride 15 |
| Global OBIS target group | 21,789,311 records | effort-weighted sample off one 1.4 MB call |

Three findings worth keeping:

- **The post-2014 label drought is global, not regional.** Yellowfin worldwide:
  67,780 records 2000–2013 vs 772 after; bigeye 29,982 vs 59. So
  `HABITAT_END = 2013` stands worldwide and going global buys ~170x the labels
  *inside* the existing window (~117,000 vs ~800), not a longer one. It buys
  nothing for the two Indian coastal species — oil sardine has 112 records
  worldwide and every one is already inside `NORTH_INDIAN_OCEAN`.
- **The OBIS pager would have truncated silently.** At the page cap it returned
  the first 1M records by `after` cursor — an *ordered*, spatially skewed
  prefix, which for a pool whose job is representing survey effort is worse
  than no pool. It raises now, and `sample_target_group` is the affordable
  path.
- **Memory, not network, was the binding constraint** on a 9 GB machine.
  `sample_at_points(batch_years=True)` fixes it, and is value-identical rather
  than just cheaper — verified by a test comparing it against the unbatched
  path column for column, which fails (`thetao` off by 2.92) if the ±45-day
  slice pad is removed. Eddy kinetic energy needs the record mean passed in for
  the same reason: it is the one derived field that reduces over time.

HAB stays **multi-region rather than global**, decided on arithmetic: the same
six years worldwide at 0.25° is ~1.6 billion rows and ~650 GB, most of it
open-ocean rows that are near-constant negatives. `config.HAB_REGIONS` has five
boxes; only the Arabian Sea control has data so far.

Remaining: run the other four HAB regions (one fetch each), and validate the
global PFZ model against the regional one **on the regional holdout** — a
global model that scores well on a global average can still be worse over the
Indian Ocean, which is the region that matters here.

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

## 7. Vector-field particle layers — remaining work

Shipped 2026-08-12: live ocean currents as a particle layer beside wind, and
the serving path for forecast currents. `services/vector_field.py` is now the
one place a U/V field is encoded for the GPU, and `VectorFieldParticleLayer`
takes the field's geographic frame and visual speed scale as config rather than
assuming wind's. See CLAUDE.md for what was load-bearing about that.

What is left, roughly in the order it unblocks things:

### Build the `current_u` / `current_v` forecast grids

The forecast currents layers are complete and tested but **do not appear**,
because only three grids exist on disk (`bottom_temperature`, `chlorophyll_a`,
`current_direction`). Both models are already trained.

```bash
python scripts/build_forecast_grid.py --variable current_u
python scripts/build_forecast_grid.py --variable current_v
```

Budget ~50 min for the first and much less for the second — the whole-globe
Copernicus reads are disk-cached for 6h and both variables draw on the same
physics dataset, so the second build pays for the cell loop only.

Until then `/api/tiles/forecast/vector/catalog` returns the pair with an
explicit reason and the frontend hook logs it, rather than the layer silently
not existing. Note these two are in the 13 variables affected by the
mixed-cadence merge bug below, so if that retrain happens first, build after it
and the grids only get made once.

### `wind_u` / `wind_v` — configured 2026-08-13, awaiting a training run

There is no forecast wind particle layer and there **cannot** be one from
`wind_speed` + `wind_direction`: direction is circular while every step to the
screen is linear (see the circular-variable entry under Bugs), so a vector
composed from those two grids flows backwards along every wrap. The fix is to
forecast the components directly, exactly as currents already do.

Steps 1, 2 and 4 are done — `wind_u`/`wind_v` are registry entries (from the
Copernicus wind provider's `eastward_wind`/`northward_wind`, which it already
served), YAML blocks carrying `wind_speed`'s covariates, and a `VectorPair`.
The pair is registered **before its grids exist, deliberately**: the catalog
reports it with an explicit reason (`no forecast grid for 'wind_u'. Build it
with: ...`) and the frontend hook logs that, which is a better answer than a
layer silently not existing.

What remains is step 3, which is machine time rather than code:

```bash
python scripts/train_forecasting.py --variable wind_u
python scripts/train_forecasting.py --variable wind_v
python scripts/build_forecast_grid.py --variable wind_u
python scripts/build_forecast_grid.py --variable wind_v
```

Apply the usual bar to the training log — skill > 0 *and* ≤1 of 5 folds
negative, read from `metrics.json` rather than the aggregate line. The same move
would make `wind_direction` a derived field rather than a trained one, which is
the better answer for it anyway.

### Verify the animation in a real browser

Everything up to and including the texture and its sampling math is verified
against live data — `tests/test_vector_field.py` reimplements the shader's
`fieldUV()` in Python and asserts the encoded texture decodes back to the input
velocity, and the live fetch was checked against known features (Gulf Stream
1.44 m/s NE, Agulhas 0.54 m/s SW, no data below 80°S). **The moving pixels
themselves have not been seen.** Browser tabs driven from the agent harness are
always hidden, so `requestAnimationFrame` never fires, the map never
initialises and every animation freezes — this is a limitation of the harness,
not evidence of a problem. Needs one human look at `/map` with the Ocean
Currents layer on.

Worth checking at the same time: two particle systems running at once (wind +
currents) on a mid-range GPU. Each is an independent
`requestAnimationFrame` + `map.redraw()` loop with its own trail framebuffers
at drawing-buffer resolution, and nothing currently coordinates them.

### Other fields the engine could now carry

Cheap, since the engine is generic and the encoder is shared — each is one
service + one registry entry:

- **Stokes drift / wave direction** from `GLOBAL_ANALYSISFORECAST_WAV_001_027`,
  which the downloader already integrates. Same circular caveat: use the
  component fields if the product carries them.
- **Depth-resolved currents.** `uo`/`vo` exist on all 50 levels of the daily
  product; a depth selector on the currents layer would be a genuinely
  different view of the same integration, and the server-side depth bound
  documented for the 50-level products applies.

---

## Bugs and correctness

### ~~Mixed-cadence merge sampled fine providers instead of averaging them~~ (fixed 2026-08-10)

`cleaning.py::build_dataframe` merged providers and *then* resampled. The merge
is `xr.merge(join="inner")` on time, which keeps the coarse provider's
timestamps — so an hourly field paired with a daily one survived as its 00:00
sample, and the later resample averaged a single value per day. Every row
carried an instantaneous reading where a 24-hour mean was intended.

Silent by construction: nothing raised, nothing was NaN, the units and
magnitude were right, and the error is systematic rather than noisy. On a
synthetic 3 °C diurnal cycle the old path returned **23.0 where the daily mean
is 20.0** — wrong by the full amplitude, in the same direction, in every row.

**13 of the 32 configured forecasting variables trained on this**: all five
wave variables (3-hourly target against hourly wind), all seven
biogeochemistry variables (daily target against hourly SST), the three
depth-resolved ones (`water_temperature`, `water_salinity`,
`bottom_temperature`) and `sea_level_anomaly`.

Fixed by reordering `build_dataframe` to **resolve codes -> aggregate per
provider -> merge**. Aggregating before the join means the axes already agree
when it runs, so the intersection only drops genuinely uncovered periods.
Resolving codes first keeps non-linear derivations on native samples —
`current_speed` is `hypot(uo, vo)`, and a current rotating through the day at
a constant 1 m/s averages to ~0 components. The post-merge resample is gone;
two places defining the cadence is how the earlier one stops mattering.
`tests/test_download_cadence.py` pins all of it (the first test fails against
the old implementation with exactly the 23.0/20.0 split).

Consequences, neither of them done:

- **Those 13 variables should be retrained.** Their covariate columns changed
  value. Nothing is *unsafe* about the shipped models — they are
  self-consistent, trained and served on the same features — but they are
  fitted on a covariate that misrepresents its own day. Retrain after the
  daily-product question below settles, so the features change once.
- The three built grids (`bottom_temperature`, `chlorophyll_a`,
  `current_direction`) are all in the affected set and should be rebuilt with
  the models.

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

### ~~The habitat / bloom-risk tiles still erode their coastlines~~ (fixed 2026-08-13)

`forecast_tiles` was fixed 2026-08-12 and `predictions.py` on 2026-08-13. The
defect: a plain bilinear read of a NaN-holed grid is poisoned by the hole, so
every pixel with a land cell among its four neighbours came back NaN, the
painted ocean retreated a full cell from every coast, and the edge fell on the
grid's own axis-aligned steps. Measured on the shipped chlorophyll grid:
**3,609 of 42,499 ocean cells (8.5%) erased** — the coastal band the layer is
most about. On the ML grids the exposed band is **698 of 15,765 habitat cells
(4.4%)** and **196 of 1,761 bloom-risk cells (11.1%)**.

The sampler now lives in **`services/field_sampling.py`**, imported by both,
rather than being copied. Two things came out of making it shared, and both are
load-bearing:

- **The longitude wrap had to become conditional.** `forecast_tiles`' version
  wrapped both ends unconditionally, which is right for a global cell-centred
  grid (−179.5 to 179.5 at 1°) and *catastrophic* for the ML grids, which are
  regional — habitat spans 55–95°E, bloom risk 68–78°E. Wrapping those splices
  the Bay of Bengal onto the Arabian Sea coast. `is_globally_periodic` measures
  the span from the cell edges instead of assuming.
- **Angular resampling landed here too**, since it is the same interpolation
  step. See the circular-variable entry below.

Verified against the real exports: covered cell centres sample to their own
value with **0.0** error, so `point()`'s nearest-cell answer still agrees with
the pixel.

### Circular variables — rendering and legend fixed 2026-08-13, modelling still open

`current_direction`, `wind_direction` and `wave_direction` are degrees on 0–360.
Every stage between the model and the screen was linear, so a wrap through north
was averaged rather than wrapped. Verified on the shipped grid 2026-08-12:
values span 0.31–359.97, so the wrap is populated and the artefact was live.

**Done (2026-08-13) — everything between the trained model and the screen:**

- **Resampling** interpolates `sin`/`cos` separately and recombines with
  `atan2` (`field_sampling.build_sampler(angular=True)`). The defect is pinned
  by a test that still asserts the *linear* path returns 180 for the midpoint of
  359 and 1 — the exact opposite heading.
- **`change` mode** uses `angular_difference`, a signed veer wrapped to
  [−180, 180). A 5° veer across north was reading as −355 and clamping to the
  cold end of a ramp reaching ±80; it now reads +5. The point panel uses the
  same function, so the number and the colour agree.
- **Legend and scale.** A cyclic ramp (`CYCLIC_STOPS`), whose first and last
  stop are the same colour by construction, on the bearing's true 0–360 domain
  rather than the grid's percentiles. Hue at fixed lightness rather than a
  perceptual cyclic map like twilight, because twilight passes through
  near-black at a quarter turn and this repo has already measured what that does
  over the Abyss basemap (1.13:1). Every stop here clears **3.34:1**, and
  opposite headings stay ≥246 apart in RGB.
- **Grid metadata.** `grid_predictor` writes 0–360 and a ±180 change scale for a
  bearing instead of running percentiles round a circle — which is where
  `display_max: 400` came from. The tile catalog also reports the geometric
  bounds for circular variables regardless of what an older grid file stored, so
  grids built before this change render correctly without a rebuild.
- **One source of truth.** `circular` is a `VariableInfo` field in the download
  registry; `VariableConfig.circular` now *inherits* it rather than restating it
  in YAML, exactly as label/unit already do. It was briefly declared in both
  places, and the two disagreeing is the bug worth designing out — the modelling
  half would encode sin/cos while the rendering half painted a linear ramp.
- **`wave_direction` had the same problem** — it is configured the same way and
  trained in the same batch, and it is fixed by the same change.

**Still open — the modelling half.** The model regresses on the level, and with
`target_mode: delta` that makes the target the *change* in degrees, so a 5° veer
across north is still a −355° training target. The fix is to predict the
components and derive the angle, which is what `current_u`/`current_v` already
do — and is why the currents *particle* layer was never affected. That would
make `current_direction` and `wind_direction` derived fields rather than trained
ones. `wind_u`/`wind_v` are now configured (see §7); the training run is what
remains.

### ~~Fish-habitat ensemble scores below its own best member~~ (fixed 2026-08-13)

Members were weighted by **normalized CV TSS**, which compresses a large quality
gap into a small weight gap: because TSS is 0 at chance and the floor is 0, the
weights were proportional to the raw scores, so MaxEnt's 0.619 — 75% of
LightGBM's 0.826, but less than *half* as good on the holdout — collected 27% of
the vote. The exported product (`habitat_suitability.nc`) is the ensemble, so
this was a property of what gets served.

Weighting is now a **softmax over CV TSS** at temperature 0.05, chosen so the
two interchangeable leaders (0.826 and 0.821, a tenth of a temperature unit
apart) stay comparable while MaxEnt, four units back, falls out. Measured on the
same folds and the same fitted members, changing only the rule:

| rule | weights (lgbm / rf / maxent) | holdout TSS | Boyce | ROC-AUC |
|---|---|---|---|---|
| proportional | 0.364 / 0.362 / 0.273 | 0.694 | **0.936** | 0.917 |
| softmax | 0.519 / 0.473 / 0.008 | **0.792** | 0.905 | **0.944** |

The ensemble is finally above every member (0.792 against LightGBM's 0.788), if
only by 0.004. **The cost is real and is why the temperature is a named
constant, not a literal:** Boyce falls 0.936 → 0.905, so the old ensemble was
the better spatially *calibrated* surface. It is still better calibrated than
LightGBM alone (0.895), so the trade does not take the ensemble below its best
member on either axis — but it is a trade, and it is now made explicitly rather
than by a normalisation constant. `proportional` is kept so the earlier baseline
reproduces exactly, and the rule is logged per run to the tracking store.

Models, reports and `exports/*.nc` were regenerated, and the docs chapters carry
the new numbers. Still open from the original note: **stacking on out-of-fold
predictions** is the more principled version and was not attempted.

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
miss costs more than a false alarm, and **now recorded as a decision rather than
left implicit** (2026-08-13): the layer is named `Bloom Risk (+7d, screening)`
in the picker, and its attribution carries the per-horizon operating point
(+3d precision 0.449 / +5d 0.280 / +7d 0.202) with an explicit "use it to decide
where to look, not that a bloom is happening". The horizons no longer sit in a
dropdown looking interchangeable.

### ~~Small habitat holdout~~ — both now reported (2026-08-13)

885 rows / 167 positives, so the confidence interval on a single holdout number
is wide. Re-measured from the fold scores: LightGBM's five spatial folds carry
**397–791 rows each and TSS 0.757–0.898** (the earlier note said 471–791; fold 5
is 397). The map layer's attribution now states the fold range *and* the holdout,
and says which one to trust — a lone number implies precision this does not have.

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
