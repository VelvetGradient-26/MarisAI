# Done

Completed work, and **the findings that outlived it**. Nothing here is a task.

This file exists because most of what was learned building MarisAI is only
legible as the residue of finished work: a measured number, a decision with its
reason attached, or a mistake worth not repeating. TODO.md holds pending work
only; anything that ships moves here with its evidence rather than being
deleted.

Numbers were measured, not estimated. Re-verify before relying on any of them if
it has been a while.

---

## Forecasting engine

### `wind_u` / `wind_v` — trained 2026-08-15

Both variables ship at all four horizons, 0 of 5 folds negative everywhere:

| | h1 | h3 | h7 | h30 |
| --- | --- | --- | --- | --- |
| `wind_u` | +0.217 | +0.301 | +0.385 | +0.398 |
| `wind_v` | +0.300 | +0.366 | +0.398 | +0.450 |

Forecast wind particles ship on top of them. Both grids carry **no covariates at
all** — `pressure` and `air_temperature` are Open-Meteo, a point API, so no
global field for them can exist — and `missing_covariates` names them in the
layer attribution, because LightGBM routes an absent feature down its
missing-value branch without complaint and the map would otherwise look exactly
as confident as a complete one.

**A dependency recorded as blocked was not.** This entry claimed upwelling was
waiting on these models. Upwelling needs wind *components*, and
`copernicus_wind.snapshot()` had exposed live `u`/`v` all along for
`services/drift.py` to sum; the training run produced *forecast* grids, which is
a different thing and the wrong footing for a detector. **Check what a dependency
actually needs before recording it as blocked.**

### The `--all` grid build — complete

Verified on disk 2026-08-17: 28 grids; the only 5 trained variables without one
are the Open-Meteo point-API variables `grid_history.ungriddable_reason` already
refuses. **0 grids stale** against their models. Count the directory, never a
number in a document — it was 8 on 2026-08-14 and 28 two days later.

### The 13 mixed-cadence variables — retrained 2026-08-15

`cleaning.py` merged providers and *then* resampled, so an hourly covariate
paired with a daily target survived as its 00:00 sample standing in for a 24-hour
mean. On a synthetic 3 °C diurnal cycle the old path returned **23.0 where the
daily mean is 20.0** — wrong by the full amplitude, in the same direction, in
every row, with nothing raised. Fixed by reordering to resolve codes → aggregate
per provider → merge.

**Skill then moved by less than ±0.03 everywhere, in no consistent direction**
(worst: `chlorophyll_a` h30 −0.028, `nitrate` h7 −0.030). That does not make the
fix wrong — the old path provably misrepresented a daily mean — but it answers
"how much was riding on it": on these series, the difference between a
covariate's daily mean and its midnight sample does not propagate into forecast
skill. Worth knowing before budgeting a retrain against a similar find.

**The rejections reproduced, which is the more interesting half.** A retrain
trains every *configured* horizon and has no concept of rejection, so the batch
silently resurrected six horizons deleted on their own merits — and all six
failed again with the same signature. The 2026-08-10 rejections were signal, not
fold noise. `scripts/apply_shipping_bar.py` makes the check mechanical: it reads
`metrics.json` rather than the aggregate log line, and **moves** failures to
`_rejected/<date>/` because the artifact is the evidence for the decision. Run it
after every batch retrain; nothing else catches a resurrected horizon.

### Circular variables — closed 2026-08-17

Everything downstream of the model had handled bearings since 2026-08-13
(sin/cos resampling recombined with `atan2`, a signed veer wrapped to [−180,
180), a cyclic ramp on the true 0–360 domain, `circular` living only in
`VariableInfo`). **The model itself was still linear**: with `target_mode:
delta` a 5° veer across north trains as −355, teaching an excursion that never
happened and leaving no trace — the model fits, scores and returns bearings in
range.

`current_direction` and `wind_direction` are now assembled from their forecast
components (`forecasting/derived.py`). The grid path combines two existing
component grids in **~1 second instead of ~25 minutes**; verified on the real
grids, 200 random ocean cells agree with the point path to **0.0e+00 degrees**
with NaN structure matching the components exactly. The interval is propagated
through `atan2` rather than copied, so a faster vector gets a tighter bearing —
and it widens to the full circle as the vector vanishes, because slack water
genuinely has no heading.

**`wave_direction` stays trained** and still carries the linear-target flaw: the
registry has no wave components to decompose. That asymmetry is stated in the
catalog rather than hidden.

### `current_direction` was reported in the wrong convention — fixed 2026-08-17

`cleaning.py::_derive_direction_to` returned the bare mathematical angle,
`degrees(atan2(v, u))`, where a compass bearing is `90 − that`:

| flow | downloader (old) | live map layer |
| --- | --- | --- |
| east | 0 | 90 |
| north | 90 | 0 |
| west | 180 | 270 |
| south | 270 | 180 |
| north-east | **45** | **45** |

Water flowing due east was reported as due north — in range, smooth, and wrong
everywhere except the 45° diagonal, which is the one test vector a person is
most likely to try by hand. The sibling `_derive_direction_from` was never
affected: `270 − angle` is `(90 − angle) + 180`, the correct bearing plus the
half turn that makes it a "from". **The two derivations sit three lines apart and
only one was wrong**, which is why it survived. It reached the downloader's CSV
exports, the trained model and its grid; the model is retired to
`_rejected/20260817/` and the grid rebuilt from components.

### Rejections to respect, not retry

A horizon ships only if **overall skill > 0 AND at most 1 of 5 folds is
negative**. The second clause is load-bearing: *six* rejected horizons print
`beats persistence` on the aggregate line.

- **`sea_surface_salinity` — dropped entirely.** h3 −0.152, h7 −0.118.
- **`water_salinity` h3/h7 deleted, h1+h30 kept.** Same physics, different
  evidence: h1 is +0.179 with 0/5 folds negative and tightly clustered.
- **`bottom_temperature` h1 only.** "Forecastable a day out, not beyond."
- **`humidity` h1 deleted.** −0.020, 2/5 negative (one at −0.435).
- **`nitrate` h3 deleted**, then legitimately returned at +0.103 (1/5 negative).
- **`sea_level_anomaly` h7/h30 deleted.** Both printed `beats persistence`
  (+0.073, +0.111) with **2 of 5 folds negative** — the cleanest demonstration
  in the repo of why the second clause exists.

Weakest thing kept: `diffuse_attenuation` h3 at +0.026 (1/5 negative). Revisit it
first if the bar is ever tightened.

### The daily-Copernicus question — settled 2026-08-15: **do not swap**

Measured through the real fetch path on a 10-day window:

| | s/timestep | a 45-day grid window |
| --- | --- | --- |
| hourly physics, thetao+so | **0.89** | 1080 reads = **15.9 min** |
| daily thetao, depth-bounded | **1.16** | 45 reads = **0.9 min** |
| daily thetao, *no* depth bound | 8.63 (2-day window) | 45 reads = 6 min |

Daily is ~18x cheaper, not the ~40x on record, and hourly costs ~16 min rather
than ~35. **Every earlier figure was wrong in both directions** — a short window
is dominated by per-request overhead (the same daily read measured 3.89
s/timestep over 2 days and 1.16 over 10), which is how a probe produces a number
that reverses a ranking.

Rejected anyway, on grounds cost does not settle: it would cost the downloader
`Resolution.hourly` for the seven variables on `copernicus_physics`, turn one
provider into three, and force a full retrain of everything carrying SST /
salinity / currents as a covariate. Revisit only if the grid builder becomes
fetch-bound again, or if a *new* variable needs a daily-only field.

---

## Detection

### The climatology — built 2026-08-17

`services/climatology/` holds a per-cell, per-day-of-year **percentile** stack.
1991–2020, 1°, 271 MB, 30 years fetched in ~25 min and fitted in 761 s.

**The cost was mis-stated as "the expensive global fetch path", and that path
cannot supply it at all.** Every Copernicus provider starts recently — physics
2022-06-01, waves 2022-11-01, wind 2024-06-13, BGC 2021-11-01 — so a 30-year
baseline is not expensive there, it does not exist. **NOAA OISST v2.1** is on the
same CoastWatch ERDDAP `crw.py` already uses: daily 0.25°, 1981-09-01 onward, one
year strided to 1° is **94.6 MB in 51 s**.

Verified against the raw record rather than trusted: a hand-computed p90 at
20.1°N 65.1°E day 200 over 290 pooled samples matches the stored value exactly
(29.6130 / mean 28.4055); the seasonal cycle is hemispherically opposite; global
p90 spans −1.80…35.68 °C.

Four things learned, each from getting it wrong first:

- **A 5-day probe measured 8.9 s and would have predicted ~11 min per year** —
  13× off. Per-request overhead dominates a small griddap request.
- **Retry backoff of 2 s/4 s lost the first run inside six seconds**, to a host
  that had served the identical URL twenty minutes earlier. CoastWatch flaps on
  the ~100 s scale, so a policy tighter than the flap cannot outlast one — it
  converts a recoverable outage into a failed job while adding load.
- **Short years are the archive, not a truncated response.** 1991 returns 365
  days and 1993 returns **163**; re-fetching 1993 healthy returns the identical
  163, and the dataset reports `evenlySpaced=false` over 15,210 values across
  ~16,400 days — **~1,200 days genuinely absent**. A per-year completeness check
  written against the wrong diagnosis would have rejected a real baseline
  forever. What protects a percentile is a floor on samples per *estimate*.
  Completeness of the shipped fit: **89.3%**.
- **`p90 >= mean` is false** on 1,940 of 15,761,058 finite cells. Median
  violation 5e-06 °C (float32 rounding); the largest on the Antarctic ice margin,
  where the sample is pinned at the freezing point with warm excursions — a
  right-skewed sample legitimately puts its mean above its 90th percentile.
  `p10 <= p90` does hold and is the ordering worth testing.

Two constructions in the fit are load-bearing and silent when wrong: the
day-of-year index is **leap-adjusted** (pandas puts 1 March at 60 in a common
year and 61 in a leap one), and the pooling window **wraps the year**.

### Eddy detection — shipped 2026-08-15

`services/eddies.py`, Okubo-Weiss (W < −0.2σ) over the live surface-current
cache. **2,097 features globally**, densest exactly where they should be (Gulf
Stream, Kuroshio, Agulhas, the Somali Great Whirl), median radius ~55 km, whole
pass **0.1 s**.

- **Never loop `np.nonzero(labels == index)` per component** — that rescans the
  grid once per feature, measured **37 s** at global scale. Sorting the labelled
  cells once and slicing gives a bit-identical answer in 0.1 s.
- **Polarity is `sign(ζ) == sign(latitude)`**, not `sign(ζ)`: a detector reading
  the vorticity sign alone is right in one hemisphere and confidently wrong in
  the other.
- **On white noise it still returns features** — a relative threshold always has
  cells below it — but every one comes back at the 40 km floor. A *large*
  detection is evidence of real structure; a small one may not be.

### Marine heatwaves — shipped 2026-08-17

`services/heatwaves.py`, to the Hobday definition: SST above the
seasonally-varying 90th percentile for **at least five consecutive days**,
categorised by multiples of the mean-to-p90 gap.

End-to-end on real data: **9,003 of 31,830 ocean cells (60°S–60°N), 28.3%**,
mostly moderate and 16 extreme. That looked high, so it was checked rather than
assumed: **35.0% of cells are above p90 on the latest day alone**, so the
five-day clause removes 6.7 points and is doing its job. The remainder is genuine
warming against a fixed 1991–2020 baseline — which a fixed baseline reports more
of over time by construction, and the layer says so.

Each day is compared against **its own** threshold: over a 30-day window in
spring the seasonal p90 moves measurably, and reusing the latest day's threshold
biases run length in whichever direction the season is going.

### Coastal upwelling — shipped 2026-08-17

`services/upwelling.py`, Bakun's index: Ekman transport from bulk wind stress
projected onto the offshore normal. Reads the live wind and currents caches.

- **The coastal normal is derived from the currents field's own land mask**
  (smooth the ocean mask, take its gradient), because no service supplies
  coastline geometry. Coarse at ~0.25°, so `coastline_confidence` reports how
  well-defined each normal is and an ambiguous cell is dropped rather than given
  an invented bearing. The mask cannot come from the *wind* field — wind is
  defined over land, so its coverage edge is the whole globe.
- **The hemisphere asymmetry falls out of the sign of f**, never a latitude
  branch.
- **A test fixture caught a mistake worth keeping.** The first one put land to
  the west and called it an eastern boundary. That is a *western* boundary, where
  an equatorward wind correctly downwells — so the physics was right and the
  geometry was backwards. Had the code been "fixed" to match, every upwelling
  coast would have been reported as downwelling, in an entirely plausible field.
- **Not corroborated against SST or chlorophyll**, deliberately: Bakun's index
  says the wind is favourable, not that cold nutrient-rich water surfaced.

### All three detectors reach the UI — 2026-08-17

Two GeoJSON cell layers in the `flow` category plus status chips, because **a
blank ocean is the most likely output of either layer and it is a result**. The
brief gained a "Detected events" section and an upwelling row; `compare.py`
inherits both. A censored run says "or more" rather than claiming a duration the
window cannot support.

**A 404 that no retry could fix**: `refresh_cache` asked for a date range ending
today, but OISST publishes with a lag (coverage ended 2026-08-01 on 2026-08-17),
and a griddap range past the dataset's end answers 404 — indistinguishable by
status code from the reload 404 the module deliberately retries. Every refresh
burned five attempts and ~8 minutes of backoff. Fixed by asking in index space
with `last`, letting the dataset name its own end.

---

## Machine learning

### The HAB regions — all four run

All of `california_current`, `benguela`, `baltic_sea` and `bay_of_bengal` are
trained beside the `arabian_sea` control. Thresholds and climatology stay fitted
**per region** — they define what counts as a bloom.

| region | base rate | t+3 precision | t+7 precision | t+7 lift |
| --- | --- | --- | --- | --- |
| arabian_sea (control) | 0.076 | 0.449 | 0.202 | +0.053 |
| bay_of_bengal | 0.078 | 0.461 | 0.187 | **+0.150** |
| baltic_sea | 0.139 | 0.699 | 0.416 | — |
| benguela | 0.154 | — | 0.566 | +0.111 |
| california_current | 0.266 | — | 0.844 | +0.076 |

**Base rate does not explain the Arabian Sea.** With three regions the spread
read as prevalence. The Bay of Bengal breaks that: **the same base rate (0.078 vs
0.076) and roughly 3x the lift**. A neighbouring basin at identical prevalence
forecasts substantially better, so the Arabian Sea is genuinely the hard region
rather than the low-prevalence one — a physical question, not an artefact.

Quote both framings: **a user experiences precision**, four-in-five false alarms
being unusable however good the lift, while **a modeller has to judge lift**
because a high base rate makes precision cheap.

**HAB stays multi-region rather than global on arithmetic**: the same six years
worldwide at 0.25° is ~1.6 billion rows and **~650 GB**, most of it open-ocean
rows that are near-constant negatives.

### The global PFZ model is worse over the Indian Ocean — measured 2026-08-15

Scored on **identical rows** (the regional model's own spatial-block holdout, 885
rows / 167 presences):

| | TSS | PR-AUC | ROC-AUC | Boyce |
| --- | --- | --- | --- | --- |
| regional model | **+0.798** | **+0.804** | **+0.945** | **+0.923** |
| global model | +0.448 | +0.489 | +0.790 | +0.721 |

The global model loses 0.35 TSS on the water this platform exists for, despite
training on 123,104 rows against 1,902. **The regional models stay the baseline
and the served artifact.** Going global buys ~170x the labels and spends them on
the wrong ocean.

Two things make the comparison trustworthy: the two shipped reports score
different water and cannot be compared, and the shipped global model was trained
on this water, so `scripts/validate_global_on_region.py` refits it with the
regional holdout's spatial **blocks** removed (blocks, not rows — a global point
50 km away is the same water).

### Fish-habitat ensemble — softmax weighting, 2026-08-13

Members weighted by a **softmax over CV TSS** at temperature 0.05 rather than
proportionally; the ensemble is finally above every member (0.792 against
LightGBM's 0.788). **The cost is real and is why the temperature is a named
constant:** Boyce falls 0.936 → 0.905, so the old ensemble was the better
spatially *calibrated* surface. `proportional` is kept so the earlier baseline
reproduces exactly.

### Per-member experiment tracking — 2026-08-17

Ensemble members are nested MLflow runs rather than flattened metric names
(`cv_tss_lightgbm`, `holdout_boyce_maxent`). Flattened is legible in one run and
useless across runs: MLflow cannot sort, filter or plot by a member when the
member is part of the key. Each member also carries the weight it drew beside its
own quality — the pair that motivated the softmax change.

### HAB t+7 sits at the edge of usefulness

At the 0.8-recall operating point: precision 0.202, false-alarm rate 0.798.
Defensible for a screening tool where a miss costs more than a false alarm, and
recorded as a decision: the layer is named `Bloom Risk (+7d, screening)` and its
attribution carries the per-horizon operating point (+3d 0.449 / +5d 0.280 / +7d
0.202). **Not a bug — listed because it constrains anything built on top of it.**

---

## Platform

### Observability — the request was a bug report

Two logging systems had grown side by side (loguru in 13 modules, stdlib
`logging` in 31) and *nothing in the server process configured either*:

    logging.getLogger("services.forecast_tiles").isEnabledFor(logging.INFO)  -> False
    logging.getLogger().handlers                                             -> []

Every `logger.info(...)` in 31 modules was discarded at source, including most of
the forecasting engine and the whole chat agent. **This codebase's silent
failures need the log to be the mitigation**, since the caches are
fire-and-forget tasks whose exceptions asyncio swallows. If a second logging
library ever appears, it has to route into the configured one rather than sit
beside it.

### Also shipped

| | outcome |
|---|---|
| globe click | Rotates toward a clicked point out near the limb, past a screen-space threshold. |
| field documentation | Two chapters in an "Ocean & atmosphere" docs group. |
| backend strays | `test.py`, `others/`, `dependencies/` gone; runtime state moved to `backend/data/`. |
| README | Rewritten. It described the product as "a single interactive map". |
| branches | 8 remote branches to 1; the prototype preserved as tag `prototype-2026-07`. |
| motion foundation | A motion budget in `styles/tokens.css`, `useReveal` promoted to `hooks/`, applied to the compare page. |

### Regrouping `services/` — deliberately not done

Measured before deciding: the 31 flat modules are referenced from **222 import
sites**, several as grouped `from services import (a, b, c)` blocks. The taxonomy
is genuinely arguable (`forecast_tiles` is as much delivery as derived field) and
CLAUDE.md documents the flat layout as the convention. A large, history-obscuring
rename imposing a debatable grouping over a documented one is a bad trade. If
ever taken up: one mechanical commit, no behaviour change, prose in the same
commit, and settle the taxonomy first.

Likewise **`models/` was not renamed** despite colliding with `app/models/`; the
README's structure listing disambiguates them, which buys most of the clarity for
none of the risk.

### The botocore connection pool — 2026-08-17

copernicusmarine builds its S3 client without `max_pool_connections`, so it
falls back to botocore's default of 10 while the zarr read fans out wider —
producing "Connection pool is full, discarding connection" once or twice a second
for every fetch. Nothing is lost; the cost is a fresh TLS handshake per discarded
connection. There is no upstream setting, so the lever is botocore's mutable
`Config.OPTION_DEFAULTS`. Raising the `urllib3` log threshold was rejected: it
hides every urllib3 warning, including the ones worth reading when CloudFerro
flaps, and leaves the handshakes in place.

---

## Hazards that will bite the next person

- **Partial success is the more dangerous failure mode.** Training the full
  variable set in one day exceeds Open-Meteo's free quota. When it blew,
  `sea_level_anomaly` failed *loudly* (hard error, nothing written) while
  `rainfall` **degraded silently** — 10 of 24 points survived, every one
  northern-hemisphere, a different subset per horizon. A global model carrying
  lat/lon and no southern data extrapolates across the equator on the one
  variable whose seasonality inverts. **Check `skipped_points` before shipping,
  not just the metrics.** It fired again on `wind_v` h1 (21 of 24 points) and the
  run printed `beats persistence` regardless.
- **Widening what the model is shown widens what it is allowed to say.**
  `agent._ungrounded_numbers` permits every figure the model was shown, including
  the system prompt. Adding the dataset catalog made
  `GLOBAL_ANALYSISFORECAST_BGC_001_028` parse as 1 and 28, so a fabricated
  "28.4 °C" traced back to a product code and passed — a safety check that failed
  by going quiet. **Check the negative case after adding prompt context.**
- **ERDDAP hosts flap, and a 404 is not proof of permanence.** ERDDAP answers
  404 "Currently unknown datasetID" while reloading a dataset, indistinguishably
  from a removed one. **Do not "fix" `services/crw.py`'s `NOAA_DHW` id**;
  switching to a `_Lon0360` dataset would silently change the longitude
  convention while the query kept working. Note the retry policy legitimately
  differs by caller: one retry on the request path (where three cost ~8 s per
  forecast), unlimited-within-budget in an offline batch job where waiting is
  free.
- **Git LFS: a slow push may be a rejected one.** GitHub answered `GH008 —
  unknown LFS objects` (`pre-receive hook declined`) after the pre-push hook
  failed to register them. The symptom looks like a slow upload. `git lfs push
  --all origin main` uploads them, after which the ref push succeeds.

---

## Considered and rejected, with the reason

Recorded so these are not re-proposed.

- **A Fishing Opportunity Index.** Composite indices with hand-chosen weights
  have nothing to validate against — the habitat model has a holdout TSS of
  0.792, an FOI has no ground truth at all. Folding in GFW vessel activity also
  makes it circular ("fish are where the boats are"). **Ship the components side
  by side.**
- **Maritime route optimisation.** A different product, and a liability surface
  far past a dashboard if anyone navigates by it. The honest 10% version is
  *conditions along a route the user supplies*.
- **Scenario simulator ("what if SST +2 °C?").** Asks a LightGBM model fitted on
  observed covariance about a joint state it has never seen; it will answer
  confidently and meaninglessly. SHAP already provides the defensible version.
- **"Ocean digital twin."** A renaming of what the platform already is.
- **An ocean time machine scrubbing 2000–2026.** Cost mis-stated as a slider: a
  scrubbable multi-decade global map is a precomputed tile archive, not a UI
  control. The affordable version is coarse monthly means for a few variables.
- **"Open marine data API."** The API already exists; what is proposed is
  documentation, versioning and a stability contract — worth doing when there is
  an actual external consumer, since a public contract is a promise not to change
  things.
- **"RAG over ocean data."** A category mismatch: RAG retrieves from unstructured
  text; this platform's data is numeric grids. You do not retrieve SST, you query
  it. The catalog version shipped as prompt-stuffing. *Scientific literature on
  HABs is the one legitimate RAG target left*, as its own project.
- **A database for caching.** Every in-process cache is already bounded; the
  on-disk fetch cache is 4.6 MB. Memory was concentrated in a few global float64
  arrays and addressed directly (SST cache ~140 MB → ~35 MB). Redis/Mongo would
  relocate those bytes while adding a resident copy plus serialization on the hot
  path.
- **A database for the ML feature store.** Parquet is correct for wide float
  matrices: 3.9M rows × 151 columns at 1.59 GB, and a 20-column read costs 0.1 s
  against 3.5 s for the full table. If it outgrows one machine, DuckDB reads
  these same files in place.
- **3D terrain on the map.** Built and removed. MapLibre drapes raster overlays
  onto the terrain mesh, and on a bathymetric DEM that mesh is the *seafloor*, so
  SST ended up ~16 km below the camera. Sea-surface data and raised seafloor
  geometry are mutually exclusive by construction.
