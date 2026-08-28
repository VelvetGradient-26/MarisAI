# MarisAI — Forecasting Engine and Forecast Map

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

- Forecasting engine (`backend/forecasting/`, `POST /api/v1/forecast`) — one
  framework for *every* variable, not one model per variable. See its
  `README.md`; the points that will bite someone who edits it:
  - **`forecasting/config/forecasting.yaml` is the whole extension surface.**
    Adding a variable is one YAML block naming a code that
    `services/download/registry.py` already serves, plus a training run. The
    loader validates every `code`/`covariate` against that registry at import
    time, so an unimplemented provider fails immediately rather than mid-run.
    Nothing in the package branches on a variable name.
  - **This is the one place the backend carries a modelling dependency.**
    `services/predictions.py` deliberately serves *precomputed* grids so
    `machine_learning/` stays out of the import graph, and that boundary is
    unchanged. This engine answers an arbitrary (variable, point, horizon) no
    offline export could enumerate, so it runs inference in-process — hence
    LightGBM/SHAP. It does not import `machine_learning`; the leakage
    conventions are mirrored, not shared.
  - **Models regress on the *change*, not the level** (`target_mode: delta`).
    A tree cannot represent `y(t+h) = y(t)`, so on these autocorrelated series
    a level-fitted model scored *worse than persistence at every horizon
    including h=1* (skill −0.12). Delta makes persistence the constant zero,
    which a tree represents exactly: same data and features, skill went to
    +0.20. `decode_prediction` needs the latest observation as an anchor, so a
    missing final timestep is a hard error rather than a guess.
  - **The `skill_score` metric exists to stop that class of failure shipping
    silently** — it compares against persistence, and the training log prints
    `WORSE THAN PERSISTENCE`. Do not remove it.
  - **Persistence alone is an insufficient baseline, and `climatology.py` is the
    second one.** Skill against persistence *rises* with horizon on several
    variables here, which is exactly the signature of a model that has learned
    only the seasonal cycle — persistence decays with horizon, a seasonal cycle
    does not. Against a day-of-year climatology the median model is +0.958 at
    h=1 and **−0.023 at h=30**, and climatology skill declines with horizon for
    13 of 13 variables. Fit and apply are two functions and every caller fits on
    a CV fold's training rows only; the estimate pools a ±15-day circular window
    because these series are ~2.2 years long and a bare day-of-year mean would
    be an average of two samples, i.e. a strawman.
    - **The obvious reading of that result is wrong, and the correction is the
      point.** An earlier draft claimed the models had "learned what month it
      is"; a three-arm feature ablation retracted it — 10 of the 11
      beats-persistence-loses-to-climatology cases keep their skill with every
      calendar feature removed. Losing to climatology reports the *baseline's*
      strength, not the model's mechanism. Two baselines cannot diagnose
      mechanism; the ablation can. Written up in `research/` (paper, notebooks
      and the exported dataset), with `research/research.md` cataloguing what
      else this repo already holds the artefacts for.
  - **The shipping bar is applied by a script, not by the trainer**
    (`scripts/apply_shipping_bar.py`): skill > 0 **and** at most 1 of 5 folds
    negative. `train_forecasting.py` trains every *configured* horizon and saves
    each one that fits — it has no concept of rejection, so a batch retrain
    silently resurrects horizons that were deleted on their own merits, which is
    exactly what nobody would notice. Failures are **moved** to
    `models/forecasting/_rejected/<YYYYMMDD>/`, never deleted: the artifact is
    the evidence for the decision. Six horizons printed `beats persistence` on
    the aggregate line while failing the fold clause.
  - **Outlier filtering is off by default, from measurement.** Hampel flagged
    5–12% of a clean Copernicus SST series at every window/threshold tried:
    its local-scale assumption inverts on a smooth field (74 of 365 values had
    a local MAD of exactly zero *because* the field is smooth). Turning it off
    raised 7-day skill from +0.138 to +0.202. The filters remain one config
    line away for genuinely noisy observational sources.
  - **Retry only what can succeed, but 404 is not proof of permanence.**
    `history.is_retryable(exc, attempt)` walks the exception's cause chain for
    an `httpx` status: 408/425/429 and 5xx retry, 400/403/410/422 never do,
    and **404 retries exactly once**. Both halves are measured, and the second
    half corrects an earlier belief recorded here:
    - The cost half is real. Retrying a permanent failure 3x with backoff adds
      ~8s to *every* forecast, turning a warm 2.2s response into 14.5s.
    - **NOAA CoastWatch's ERDDAP was previously recorded here as having
      retired `GEBCO_2020`. That was wrong.** Re-probed 2026-08-05:
      `GEBCO_2020` returns 200 and correct depths. What actually happens is
      that the whole server flaps — it went fully 503, and `NOAA_DHW` and
      `GEBCO_2020` each 404'd for ~100s before returning to 200. ERDDAP
      unloads a dataset while reloading it and answers 404 "Currently unknown
      datasetID" meanwhile, *indistinguishably* from a removed one. Hence one
      retry: a reload window recovers, a dead dataset costs one 2s backoff.
      Verified end-to-end — 404 -> 2 attempts/2.0s, 400 -> 1, 503 -> 3/8.0s.
    - **Do not "fix" `services/crw.py`'s `NOAA_DHW` id.** It 404s during a
      flap and looks retired; it is not. The dataset search index also drops
      entries while the server is unstable, so a search that returns only
      `NOAA_DHW_Lon0360` is not evidence either. Switching to a `_Lon0360`
      dataset would silently change the longitude convention of the reported
      heat-stress region coordinates (`crw.py` fetches by *index*, so the
      query would keep working while the reported longitudes became 0-360).
  - **The bathymetry provider reads `gebco2021` from Ifremer**
    (`erddap.ifremer.fr`), not NOAA. Both work; Ifremer was chosen for being
    the newer GEBCO release and stable throughout the flapping above. Same 15
    arc-second grid, same `elevation` variable, same griddap CSV shape, ~1.5s
    for a 4x4deg box. Two things worth keeping:
    - **Ifremer's fronting Tomcat rejects an unencoded `[`** in a query with a
      400 before ERDDAP ever sees it; NOAA's server tolerated raw brackets.
      `gebco.fetch` percent-encodes the subscript brackets itself, because
      `httpx` passes them through verbatim. `tests/test_download_gebco.py`
      asserts on the emitted URL — the failure is invisible offline otherwise.
    - `predictor.predict` still drops `ocean_depth` and degrades with a note
      when bathymetry is unavailable. That is a live safety net, not dead
      code — bathymetry is a separate provider that fails independently of
      the ocean models, and one constant column is not worth failing every
      forecast at every point.
  - **Provider fetches need a timeout, not just a retry.** The worst failure
    found was not an error: a Copernicus zarr read never returned, and a
    training run sat on it for 98 minutes looking healthy — alive, no
    exception, nothing that would ever raise. `history._fetch_with_retry`
    bounds each attempt at 300s and retries per *provider* (retrying the whole
    gather would re-issue slow Copernicus reads to work around a fast ERDDAP
    blip). The retry alone matters too: one transient GEBCO 503 cost 6 of 24
    training points, a quarter of the model's geography.
  - **Every horizon must request the same fetch window.** `_point_features`
    pads by the variable's *largest* configured horizon, not the current one.
    Padding by the current horizon shifts the start date per pass, changes the
    history cache key, and silently refetches all 24 points once per horizon —
    a 4x cost that presents only as slowness. A test asserts on the emitted
    cache keys.
  - **Exactly one forward shift exists** (`add_forecast_target`); everything
    else is trailing, and a test scans the source to keep it that way. Rolling
    windows close at `t` inclusive, which is safe only because horizon ≥ 1 is
    enforced — a horizon of 0 is rejected, not merely discouraged.
  - Validation is rolling-origin with an embargo defaulting to the horizon,
    never a random split. Models are **global** (one per variable+horizon
    across all 24 configured points, with lat/lon/depth/basin as features), so
    they score arbitrary coordinates. Training is offline-only —
    `scripts/train_forecasting.py`, never triggered by a request.
- Forecast map (`forecasting/grid_history.py`, `forecasting/grid_predictor.py`,
  `services/forecast_tiles.py`, `routers/forecast_tiles.py`,
  `scripts/build_forecast_grid.py`) — the forecasting engine rendered as a
  global raster layer, in two modes: `absolute` (the predicted field) and
  `change` (forecast minus the latest observation, which is the informative
  one — the absolute field at +7d looks almost exactly like today's).
  - **The grid path is the point path with the network replaced by an
    in-memory slice.** `grid_history.GridStack.slice_point` returns the same
    `{provider: (spec, Dataset)}` shape `history._fetch_frame` builds, and the
    cell loop then calls the *same* `build_dataframe` -> `clean` ->
    `build_features` chain. There is deliberately no grid-native feature
    builder: that is how train/serve skew gets in, and a 40,000-cell loop is
    exactly where the temptation to write one is strongest.
    `tests/test_forecast_grid.py::test_grid_matches_the_point_path` compares
    the two paths cell for cell on identical synthetic inputs and is what makes
    optimising the loop safe to attempt. It agrees to 1e-6 today.
  - **The fetch is inverted, and `arco-geo-series` is why it is possible.**
    This is a third access pattern the downloader never had — whole globe, many
    timesteps — and geo-series (one global timestep per chunk) is right for it
    where `arco-time-series` would touch every spatial chunk on the planet.
    Striding happens *while the array is still lazy*: a global 0.083deg float64
    field is ~70MB per timestep per variable, so 45 timesteps of two variables
    at full resolution is over 6GB.
  - **Cost is dominated by the fetch, and the fetch does not care about the
    output resolution.** Providers come from the registry unchanged, so SST
    resolves to the *hourly* physics product and a 45-day window is ~1080
    whole-globe reads (~35 min), plus ~15 min for the cell loop at 1deg
    (22 ms/cell x ~42,000 cells). `--resolution 4.0` speeds up the loop and
    nothing else. Reads are disk-cached for 6h and shared across every variable
    drawing on the same dataset.
  - **The daily depth-resolved datasets were measured through this path on
    2026-08-15 and rejected — on cost-of-change, not on cost.** Both halves of
    the old objection recorded here were wrong. The correctness half (a daily
    axis collapsing hourly wind to an instantaneous value) is gone since
    `cleaning.py` aggregates per provider *before* the merge. And the numbers
    reversed under a proper measurement: hourly is **0.89 s/timestep** (not the
    34-46 s an earlier probe reported), so a 45-day window is ~16 min, not ~35;
    daily and depth-bounded is **1.16 s/timestep**, ~0.9 min. Daily is ~18x
    cheaper, not ~40x, and hourly is affordable. A 2-day probe of the same daily
    read gives 3.89 s/timestep — **per-request overhead dominates a short
    window**, which is how the earlier probe inverted the ranking, and the
    warning against probing a fetch path with a toy window. The depth bound is
    worth 2.2x on its own (8.63 vs 3.89 s/timestep), the same trap
    `machine_learning/` documents. It is rejected anyway because the swap would
    cost `Resolution.hourly` for the seven variables on `copernicus_physics` — a
    shipped downloader capability — turn one provider into three, and force a
    retrain of every variable carrying SST/salinity/currents as a covariate.
  - **Open-Meteo variables can never be gridded**, and this is stated rather
    than absorbed. It is a point API capped at 900 points, so `air_temperature`
    — an SST covariate, and itself a trained variable — has no global field.
    `grid_history.ungriddable_reason` lets the builder skip such a *target*
    before paying for a fetch; a missing *covariate* is recorded in the grid's
    `missing_covariates` attribute and surfaced in the layer's attribution,
    because LightGBM routes an absent feature down its missing-value branch
    without complaint and the map would otherwise look exactly as confident as
    a complete one.
  - **Legend bounds live in the grid file** (`display_min`/`display_max`/
    `change_scale`, robust percentiles rounded outward at build time), so the
    tile renderer and the frontend legend cannot disagree about what a colour
    means. The change ramp must stay symmetric or zero drifts off the neutral
    colour. SST is the one variable colour-matched to an existing observation
    layer (`_MATCHED_COLORMAPS`), because comparing the forecast against the
    observed SST layer is the first thing anyone does with it.
  - **Unforecastable water is hatched, because no colour fix was available.**
    Every ramp here bottoms out near black and the default basemap is a
    near-black ocean (`abyss.ts`'s `#030f1e`), so at the layer's 0.7 opacity the
    darkest step of each ramp measured **1.13–1.27:1** against bare basemap,
    against a 2:1 floor — a cell showing strong cooling and a cell showing
    nothing were the same pixel. Both obvious fixes were tried and rejected on
    measurement: lightening needs the diverging ends brightened ~1.9x (into
    their own next stop) and viridis's 2.4x (which turns it magenta), and *no*
    ramp end clears 2:1 even at opacity 1.0. So the distinguishing channel has
    to be texture. `anchor` is the discriminator and is already in the grid
    file — finite exactly where a latest observation existed, so anchor-finite
    + forecast-NaN is "water we can see but could not score" (hatched) while
    anchor-NaN is land or outside coverage (transparent). Keying the mark on
    the forecast alone would hatch every continent; a test asserts land stays
    clear. The hatch grey clears 2:1 against ocean, land, both ramp ends *and*
    the diverging ramp's near-white centre.
  - **The sampler is `services/field_sampling.py`, shared with
    `services/predictions.py`.** Both render tiles from a NaN-holed NetCDF grid
    and both had the same coastline defect; it is fixed once. Two properties of
    the shared version are load-bearing:
    - **The longitude wrap is measured, not assumed.** `is_globally_periodic`
      checks the span from the *cell edges* (a global 1° grid runs -179.5..179.5,
      whose centres span 359 while its cells span 360). The forecast grids are
      global and need a wrap on both ends; the ML prediction grids are
      **regional** (habitat 55-95degE, bloom risk 68-78degE) and wrapping those
      would splice the Bay of Bengal onto the Arabian Sea coast. One helper is
      only safe for both because of that test.
    - **`angular=True` interpolates sin/cos and recombines with `atan2`**, for
      bearings. See the circular-variable note below.
  - **Coverage is resampled separately from values, and that is what makes the
    coastline read.** A plain bilinear read of a NaN-holed field is *poisoned*
    by the hole — any pixel with a land cell among its four neighbours comes
    back NaN — so the painted ocean retreated a whole cell from every coast and
    its edge fell on the grid's own axis-aligned steps: ~110 km of staircase at
    1deg, and **3,609 of chlorophyll's 42,499 ocean cells (8.5%) erased**,
    which is the coastal band the layer is most about. `_build_sampler` instead
    nearest-fills the values (so coastal cells stay finite) and carries a
    separate 0/1 coverage field, thresholded at 0.5 after interpolation. The
    edge then follows the bilinear 0.5 contour — the correct nearest-cell
    footprint, cutting diagonally, so the staircase becomes a chamfer — and
    stays crisp. Feathering the alpha instead was rejected: over a near-black
    basemap a soft edge reads as haze, not as land. Ocean cell centres still
    sample to their own value exactly (verified, 0.0 error), so `point()`'s
    nearest-cell answer still agrees with the pixel.
  - **The longitude wrap goes on *both* ends here, unlike SST's.** Copernicus's
    native grid starts at exactly -180, so `copernicus_sst._build_interpolator`
    only has to close the east side. Forecast grids are cell-*centred*
    (-179.5 to 179.5 at 1deg), leaving half a cell hanging off each edge of the
    map, and wrapping one end just moves the seam — which is how this was
    found, by a test that passed on the dateline and failed at -180.
  - **Circular variables are handled from the model output to the screen, but
    not inside the model.** `current_direction`, `wind_direction` and
    `wave_direction` are degrees on 0-360, where 359 and 1 are neighbours.
    Everything downstream of the trained model now treats them as angles:
    resampling is sin/cos + `atan2`, `change` mode uses a signed veer wrapped to
    [-180, 180), the ramp is `CYCLIC_STOPS` (first and last stop the same colour
    by construction) on the true 0-360 domain, and `grid_predictor` writes
    0-360/±180 rather than running percentiles round a circle — which is where
    the shipped grid's `display_max: 400` came from. The tile catalog reports the
    geometric bounds regardless of what an older grid file stored, so a grid
    built before this renders correctly with no rebuild.
    - **`circular` has exactly one home**: `VariableInfo` in
      `services/download/registry.py`. `VariableConfig.circular` *inherits* it,
      the same way label/unit already do. It was briefly declared in the YAML
      too, and the two disagreeing is the failure worth designing out — the
      modelling half would encode sin/cos while the renderer painted a linear
      ramp, and both would look plausible.
    - **The modelling half is still linear.** With `target_mode: delta` the
      target is the *change* in degrees, so a 5deg veer across north trains as
      -355. The answer is to predict components and derive the angle, which is
      what `current_u`/`current_v` already do — and why the currents *particle*
      layer was never affected.
    - The cyclic ramp cycles hue at fixed lightness rather than using a
      perceptual cyclic map like twilight, for one app-specific reason: twilight
      passes through near-black at a quarter turn, and a near-black ramp measures
      1.13:1 against the Abyss basemap. Every stop here clears **3.34:1**, and
      opposite headings stay >=246 apart in RGB.
  - **Layers register at runtime, not from `layerRegistry`.** A forecast layer
    exists only where a model is trained *and* its grid built, so
    `hooks/useForecastGridLayers.ts` fetches `/api/tiles/forecast/catalog` and
    calls `LayerManager.register()` — which is safe any time, since it only
    writes in-memory metadata and emits. A newly built grid becomes a map layer
    with no frontend edit. They land in the exclusive `ocean` category, being
    full-coverage colour fields like SST.
  - Grids are built offline (`scripts/build_forecast_grid.py`) and refreshed by
    a 12-hourly scheduler job that **skips anything already fresh**, which is
    what makes the boot-time call safe. A failed rebuild keeps the previous
    grid: `save_grid` only writes after a successful build.
  - **Never quote a grid count from this file — count the directory.** The
    `--all` build runs incrementally and the number moves; it was 8 on
    2026-08-14 and **28** on 2026-08-16 (the 26 griddable variables of the
    original catalogue plus `wind_u`/`wind_v`). `ls
    backend/models/forecasting/_grids/` is the only trustworthy answer, and
    `GET /api/dashboard/data-quality` reports it alongside the trained-model
    count and the reason each ungriddable variable can never have one.
  - **`_cell_features` compares a row against the *first cell's* columns, not
    against `columns`.** `columns` is deliberately the numeric subset, and the
    feature frame always carries a `timestamp` column that is dropped by design
    — testing against it reported all 64,440 cells of a real build as carrying
    unknown columns. A warning that says "investigate before trusting this grid"
    and fires on every correct build is one nobody reads.
  - **Progress bars are opt-in and the CLI is the only thing that opts in**
    (`forecasting/progress.py`). The same `build_forecast_grid` runs from the
    API's 12-hourly scheduler job, where a bar rewriting stderr would interleave
    with request logs. `scripts/build_forecast_grid.py` also filters
    `copernicusmarine`/`urllib3` with a logging **filter rather than a level** —
    copernicusmarine reconfigures logging when it opens a dataset, so a level set
    beforehand is overwritten and every banner line appears twice.
  - **The build runs in a worker thread, and must keep doing so.** Everything
    past the fetch — `grid_predictor._score_stack`, i.e. the cell loop,
    inference and assembly — is ~15 min of CPU with no `await` in it, and the
    scheduler starts it on the server's event loop at boot. Awaited inline it
    stalls *every* request on the process for that whole window, which presents
    as a mysteriously dead API twice a day rather than as an error.
    `test_the_cell_loop_does_not_run_on_the_event_loop` asserts on the thread
    itself, because the synthetic stack builds in milliseconds and any timing
    check would pass with the work back on the loop. Same rule as
    `ocean_state.py` and `copernicus_sst.py`: new blocking work goes in the
    threaded span, new awaiting work goes in the caller.

