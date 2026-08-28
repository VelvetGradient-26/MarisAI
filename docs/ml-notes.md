# MarisAI — Machine Learning Conventions

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

## Machine learning conventions (`machine_learning/`)

- **`marine_ml/` is the shared spine; both problems import it, neither
  duplicates it.** Ingestion (`sources/`), regridding + the feature store
  (`fusion.py`), geometry/temporal feature libraries (`features/`) and the
  validation harness (`validation/`) are shared. Only labels and
  problem-specific derived features live in `hab_early_warning/` and
  `fish_habitat_prediction/`. A new shared utility goes in `marine_ml/`,
  not in one problem's `src/`.
- **Every fit-then-apply pair is two functions** (`fit_climatology`/
  `apply_climatology`, `fit_bloom_thresholds`/`apply_bloom_thresholds`,
  `fit_thermal_niche`/`apply_thermal_niche`) so fitting on the wrong rows
  takes deliberate effort. Fit on training rows only — a climatology or
  threshold fitted over the full record leaks the test period into the
  *label definition*, not just a feature.
- **Only one forward shift exists in the codebase**, the target construction
  in `hab_early_warning/src/labels.py::add_forecast_labels`. Everything in
  `marine_ml/features/temporal.py` is trailing/backward by construction.
  Keep it that way; `tests/test_leakage.py` enforces it.
- **Never random K-fold.** Use `validation/splits.py`: rolling-origin (with an
  embargo gap ≥ the forecast horizon) for HAB, spatial block CV for habitat.
  Random splits on either problem inflate every metric.
- **Copernicus fetches need a server-side depth bound.** The `_my_` reanalysis
  products carry 50 depth levels; only the surface is used. Passing
  `minimum_depth`/`maximum_depth` to `open_dataset` turns a request that
  did not finish in 15 minutes into ~60s. This is *unlike* the backend's NRT
  products (singleton depth dim, where a post-hoc `isel(depth=0)` is fine).
- **Service choice is per-call, because there are two access patterns.**
  Regional fetches use `config.COPERNICUS_SERVICE` (`arco-time-series`) —
  bounded area, many timesteps, same as the backend's downloader. The
  worldwide habitat build inverts it and uses
  `config.GLOBAL_COPERNICUS_SERVICE` (`arco-geo-series`), exactly as the
  forecast map does. Measured 2026-08-10 on one year of global monthly physics
  coarsened to 0.25°: **geo-series 7.5s, time-series 89.0s**. Pass `service=`;
  do not change the module default, which would make every regional fetch
  pathological.
- **Everything about a global region is opt-in, and that is deliberate** —
  the regional models are the baseline a global one has to beat, so their code
  path must stay untouched. Three flags, all defaulting off
  (`sources/copernicus.py`, `sources/gebco.py`, `fusion.py`):
  - `coarsen_to` block-averages to the common grid **while the array is still
    lazy**. Global monthly physics at native 1/12° is ~35 GB as one array;
    coarsened it is **135 MB per calendar year**. It bounds memory and disk,
    *not* network — Copernicus subsets server-side by bbox/time/depth, but a
    stride is applied client-side.
  - `chunk_years` caches one NetCDF per calendar year and returns them as a
    lazy `open_mfdataset`, so peak memory is one year and an interrupted run
    resumes.
  - `fetch_bathymetry(resolution=...)` strides the griddap subscript. Global
    at native 1 arc-minute is 233M cells (~930 MB in one response) and ERDDAP
    refuses it; at 0.25° it is 7.9 MB in ~5s. That host also flaps, so the
    fetch retries 503/504 **and 404** — ERDDAP answers 404 while reloading a
    dataset, indistinguishably from a removed one (same finding as the
    backend's `history.is_retryable`).
- **`sample_at_points(batch_years=True)` is a memory fix that must stay
  value-identical**, and is tested that way. This machine has 9 GB; the
  unbatched global path OOMs. Two things make batching equivalent rather than
  merely cheaper, and both are load-bearing:
  - **Slices are padded ±45 days.** The products are stamped mid-month and
    selection is nearest-in-time, so a 31 December point's nearest timestep is
    the *next* year's 15 January. With the pad set to 0 the equivalence test
    fails on `thetao` by 2.92 — verified, not assumed.
  - **Eddy kinetic energy is handed the record mean** (`add_derived_fields`'s
    `flow_mean`). It is the one derived field that reduces over time; a
    one-year batch would measure anomalies against that year's mean under the
    same column name. Every other derived field is per-timestep.
- **The OBIS target group cannot be enumerated globally.** 21,789,311 records
  worldwide against 10,051 over `NORTH_INDIAN_OCEAN`. `sources/obis.py` now
  raises rather than returning a truncated frame at the page cap — pages
  follow the `after` cursor, so truncation is *ordered*, and a spatially
  skewed prefix is the worst possible outcome for a pool whose whole job is
  representing survey effort. Use `sample_target_group`: one call to
  `/occurrence/grid/{precision}` gives per-cell counts (~7,700 cells, 1.4 MB),
  cells are drawn **without replacement with probability ∝ effort**, and an
  equal quota is taken from each. Drawing without replacement matters because
  the largest single cell holds 2.15M records, ~10% of the planet's total.
  The design follows from `labels.build_background` thinning the pool to one
  point per (0.25° cell, month) slot — records beyond the first in a slot are
  discarded anyway.
- **The global habitat model is measurably worse over the northern Indian
  Ocean, and the regional model stays the served artifact.** Measured
  2026-08-15 on identical rows (the regional holdout, 885 rows/167 presences):
  regional TSS 0.798 / Boyce 0.923 against global TSS 0.448 / Boyce 0.721,
  despite the global model training on 123,104 rows against 1,902. Two things
  make that comparison valid and both live in
  `scripts/validate_global_on_region.py`: the two shipped reports score
  *different* water and cannot be compared, and the shipped global model was
  trained on this water, so it is refitted with the regional holdout's spatial
  **blocks** removed (blocks, not rows — a global point 50 km away is the same
  water). Do not swap the regional models for the global one on a global
  average.
- **Going global multiplies labels, not the usable window.** Verified against
  OBIS 2026-08-10: the post-2014 target-species drought is **global**, not an
  artefact of the regional box (yellowfin worldwide 67,780 records 2000–2013
  vs 772 after; bigeye 29,982 vs 59). `HABITAT_END = 2013` therefore stands
  worldwide — do not reopen it on the assumption that more ocean means more
  recent labels. What global buys is ~170x the records *inside* that window
  (~117,000 vs ~800). It buys nothing for the two Indian coastal species: oil
  sardine has 112 records worldwide and all of them are already inside
  `NORTH_INDIAN_OCEAN`, Indian mackerel 243.
- **HAB precision is dominated by regional base rate, so an operating point is
  a per-region decision.** Run 2026-08-15: at the 80%-recall point, t+7
  precision is 0.202 in the Arabian Sea, **0.844** in the California Current and
  0.566 in Benguela — but the bloom base rates are 0.076, 0.266 and 0.154, so as
  a multiple over base rate the three are close (2.7-3.7x) and by lift over
  persistence the Arabian Sea is merely weakest at long lead (+0.053 against
  +0.076 and +0.111). Quote both: a user experiences precision, and a modeller
  has to judge lift because a high base rate makes precision cheap. The
  "screening only past +3d" caveat is the Arabian Sea's, not HAB's.
- **HAB is multi-region, not global, and the arithmetic is the reason.** The
  Arabian Sea store is 3.9M rows / 1.59 GB over ~1,780 ocean cells; the global
  ocean is ~736,000 such cells, so the same six years worldwide is ~1.6 billion
  rows and **~650 GB**. It would also be the wrong data: blooms are coastal and
  upwelling phenomena, so most of that would be open-ocean rows that are
  near-constant negatives. `config.HAB_REGIONS` holds the bloom boxes, Arabian
  Sea first because it is the only one with a known-good result to reproduce.
  Thresholds and climatology stay fitted **per region** — they define what
  counts as a bloom, and one region's distribution must not set another's
  labels.
- **Per-region artifact naming keeps the default bare.** Both pipelines take
  `--region`; the default region keeps its historic store/model/report names so
  the existing baselines are found unchanged, and every other region is
  suffixed. `_track` in both `train.py` files now tags the **real** region —
  it used to hardcode one, which made every run look like the same experiment.
- **Ensemble members are weighted by a *softmax* over CV TSS, not
  proportionally.** Proportional weighting is proportional to the raw scores
  (TSS is 0 at chance and the floor is 0), so a large quality gap compresses
  into a small weight gap: MaxEnt at 0.619 against LightGBM's 0.826 is less than
  half as good on the holdout and still drew 27% of the vote. The exported
  `habitat_suitability.nc` **is** the ensemble, so that was a property of what
  gets served — and it scored below its own best member (0.694 vs 0.788).
  Softmax at temperature 0.05 gives 0.792, finally above every member. The cost
  is stated rather than hidden: Boyce falls 0.936 -> 0.905, so the old ensemble
  was better spatially calibrated (still better than LightGBM's 0.895). Raise
  the temperature to trade back; `proportional` is kept so the earlier baseline
  reproduces exactly.
- **Credentials come from `backend/.env`** via `marine_ml/config.py` — don't
  add a second secrets location.
- **Region/date windows are bounded by data reality, not preference**, and
  `config.py` records why: the habitat window is 2000–2013 because OBIS
  target-species records stop after 2014; the HAB window is **2016–2021 (six
  years)** over the smaller `ARABIAN_SEA` box, because daily fields are
  non-negotiable there and *region*, not span, is what gives.
- **Experiment tracking is `marine_ml/tracking.py`, and the backend dependency
  is inverted rather than added.** Every report in this repo is written to a
  fixed filename, so each rerun destroys the previous result; runs are appended
  here instead. Both ML pipelines log automatically on `save()`. The backend
  forecasting engine is tracked *without* importing MLflow: it writes an
  immutable `_reports/runs/<timestamp>/` of plain stdlib JSON, and
  `marine_ml.ingest_forecasting` reads it from this side. That direction is the
  whole design — `backend/tests/test_training_run_record.py` asserts `mlflow`
  never appears in `backend/`, because the obvious "improvement" later is to
  log directly from the training script.
  - **The dependency is `mlflow-skinny`, never plain `mlflow`.** The full
    package pins `pandas<3`/`pyarrow<23` and would downgrade this env from
    pandas 3.0.5 / pyarrow 25 — a major-version pandas downgrade under a 3.9M-row
    parquet feature store. Skinny + SQLAlchemy is the same client; the UI runs
    out-of-venv via `uvx --from mlflow mlflow ui`.
  - **Tracking never fails a training run** (a HAB run is ~40 min) — every path
    degrades to a warning, and `MARINE_ML_TRACKING=0` opts out.
  - Fold *spread* is logged beside the mean, and `passes_bar` encodes the
    shipping rule (skill > 0 **and** ≤1 of 5 folds negative) as a metric —
    an aggregate that reads healthy over folds that include negatives is the
    failure this project keeps hitting.


