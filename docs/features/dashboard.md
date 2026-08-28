# MarisAI — Ocean Intelligence Dashboard

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

- Metric intelligence pages (`services/metrics/`, `routers/metrics.py`,
  `frontend/src/features/dashboard/metric/`) at `/dashboard/<variable>`. One
  page serves all 32 variables and contains **no variable-specific code**: it
  resolves the key against `/api/v1/forecast/catalog` and renders the section
  registry in `metric/sections.ts`, where each section declares a *capability*
  it needs (`history` / `forecast` / `explainability`) rather than a list of
  variables. A newly trained variable gets a complete page with no frontend
  edit — verified by loading `/dashboard/nitrate`, which renders fully and
  correctly omits Forecast and Explainability with the command to train them.
  - **Ocean Story computes first, phrases second.** `services/metrics/story.py`
    calculates every figure, hands the model a facts block, and *verifies the
    response*: any number not derivable from that block causes the generated
    text to be discarded for a deterministic template. The permitted set is
    derived from the block itself — an earlier hand-listed version rejected a
    faithful sentence for quoting "365 days" from its own labels.
  - **Series are decimated with a min/max envelope, never stride sampling.**
    Every Nth point erases spikes: on a 50k-point test a lone 99.0 spike and
    −5.0 trough both vanished, while the envelope preserved them exactly. A
    three-day marine heatwave inside a ten-year chart is precisely what a user
    opens the chart to find.
  - uPlot (canvas) draws the forecast and historical charts; Recharts stays on
    the small dashboard summaries. Recharts mounts a DOM node per point and
    degrades past ~5k; these charts routinely carry thousands and must stay
    interactive while zooming.
  - The dashboard's six KPI cards only map to three variables — heat-stress
    extent, bleaching risk and habitat suitability are regional derived
    indices, not point variables, and stay deliberately unlinked.
  - **`ModelDossierPage.tsx` (`/dashboard/model?variable=&horizon=`) is a
    per-artifact reproducibility view, not a metric page** — reached from
    every card on the Data Quality panel (`DataQualityPanel.tsx`). No new
    backend endpoint: it reuses `GET /api/v1/forecast/models/{variable}/{horizon}`
    and the `useModelDetail` hook `Explainability.tsx` already had, since
    `model_store.describe()` already returns everything reproducible about an
    artifact (training points, feature columns, CV folds, and the
    already-logged global SHAP importance) without unpickling the booster.
    Its Skill panel states outright that no shipped forecasting-engine model
    carries a climatology comparison — `train_forecasting.py` never calls the
    climatology path `forecasting/evaluator.py` has — rather than omit that
    row or approximate a number nothing computed. Routed as an explicit
    `/dashboard/model` branch checked *before* the generic `/dashboard/<key>`
    handler in `App.tsx::renderPage`, since that handler only matches a
    single path segment and would otherwise swallow it as `variableKey="model"`.

- Ocean Intelligence Dashboard (`routers/dashboard.py`,
  `services/dashboard/`, `features/dashboard/`) at `/dashboard`. The original
  point-analytics page moved to `/analytics` — it is not superseded, it
  answers a narrower question.
  - **The rule the whole feature is built around: never substitute a number
    for missing data.** Every KPI, live entry and provider carries
    `available` plus an `unavailable_reason`, and the UI renders the reason.
    A fabricated "0.00 mg/m³" is a false ocean reading, not a neutral
    placeholder. Endpoints return 200 with per-item unavailability rather
    than failing the page; only an unsatisfiable *request* is a 4xx.
  - **Cached, scheduled, never fetched per request** (except `trends`, which
    is inherently per-point). New sources follow `copernicus_sst.py`'s shape:
    module-level cache, `refresh_cache()` wired into `main.py`'s scheduler,
    previous data kept on failure. `services/ocean_state.py` computes its
    statistics inside the fetch thread and discards the grid — a global
    0.083° field is ~70MB per variable.
  - **`services/crw.py` (NOAA Coral Reef Watch) carries the only real
    climatology in the codebase**, which is why bleaching risk, heat-stress
    extent and SST anomaly are possible at all. Three maskings there are
    load-bearing and were each found empirically:
    - Aggregates are taken over **60°S–60°N**. Polar ice-margin cells carry
      anomalies above +15 °C (the climatology expects ice, summer retreat
      leaves water) and tripled the global mean.
    - Bleaching statistics are restricted further to **30°S–30°N**. CRW
      computes DHW on every water pixel, so the raw global maximum came from
      the St. Lawrence estuary, the Caspian and the Gulf of Finland at 40–52
      °C-weeks — non-physical for reefs and nowhere near a coral.
    - Heat stress uses **HotSpot ≥ 1 °C** (NOAA's own DHW-accumulation
      criterion), not a raw SST anomaly. `anomaly ≥ 1 °C` flagged 42% of the
      ocean and meant nothing; HotSpot flags ~13% and correctly reports zero
      across the winter Southern Ocean. Neither is the formal Hobday
      marine-heatwave definition, and every response says so.
  - **Alerts are threshold rules over real fields, not issued warnings.**
    Each carries a `basis` naming the rule and value, and the panel states
    that it is not a marine warning service.
  - **Chart coverage genuinely differs per variable** and
    `services/dashboard/trends.py` refuses (400) a range a product cannot
    serve rather than truncating: ERA5 reaches 1940, but the marine model
    carries waves from ~2022 and SST only from ~2024. The UI reads
    `supported_ranges` from `/trends/catalog` instead of assuming.
  - **KPI sparklines come from an in-process ring buffer**
    (`services/dashboard/history.py`), because no upstream can answer "what
    was the global mean SST six hours ago". It does not survive a restart,
    and a cold server shows "collecting history" rather than a flat line.
    **`services/dashboard/health.py` reuses the same buffer** for each
    provider's recent-health sparkline (`GET /api/dashboard/sources/{key}`,
    keyed `health:<provider>`, sampled opportunistically from `build()`/
    `detail()` rather than a dedicated scheduled job) — one ring-buffer
    mechanism for both, not two.
  - **Three panels' rows/cards now open a full detail page, the same
    route-per-entity pattern**: `/dashboard/model?variable=&horizon=` (a
    trained forecasting artifact, reusing the existing
    `GET /api/v1/forecast/models/{variable}/{horizon}`),
    `/dashboard/station?id=` (one NDBC buoy, `ndbc.station()`/`ndbc.raw_feed()`
    — the latter a live, uncached fetch of that station's own
    `realtime2/<id>.txt`, since a detail page is opened rarely enough that
    proof-of-provenance is worth one on-demand external call), and
    `/dashboard/satellite?layer=` (one GIBS product — no new backend
    endpoint; the preview image is built client-side from fields
    `services/gibs.py` already returns, via NASA's Worldview Snapshots API
    `wvs.earthdata.nasa.gov/api/v1/snapshot` rather than a WMTS tile, because
    `gibs.py` never persists the raw TileMatrixSet id a real tile URL would
    need — only the resolution label derived from it). All four pages share
    one `Breadcrumb` component (`features/dashboard/components/Breadcrumb.tsx`)
    rather than four near-identical copies, and are registered as exact-match
    branches in `App.tsx::renderPage` *before* the generic `/dashboard/<key>`
    prefix branch, which would otherwise swallow them.
  - **Chlorophyll, salinity and ocean heat content are charted from
    Copernicus** (`services/dashboard/copernicus_series.py`), not Open-Meteo.
    They were briefly declared impossible on an *unmeasured* assumption that
    no point source was fast enough; a 1-year daily series actually costs
    8-13s, which a 1-hour cache makes usable. These are daily products, so the
    hourly ranges are withheld for them.
  - **Ocean heat content is derived, not fetched** — `rho * cp * integral(T dz)`
    — and ships as **four layers**: 0-50, 0-100, 0-200 and 0-700 m
    (`OHC_LAYERS_M`). 0-700 m is the climate reference depth and is the wrong
    one for most marine questions: what feeds a cyclone or reads as a marine
    heatwave lives in the top ~100 m, and 600 m of near-constant deep water
    underneath averages that signal away — a warming that moves the 0-50 m
    series by >7% moves the 0-700 m series by <2%. The reference layer keeps the
    bare key `ocean_heat_content` (renaming it would break stored chart
    selections); only the new layers are suffixed. The integral **closes the
    column at the surface** — the shallowest model level is ~0.494 m, negligible
    against 700 m and ~1% of a 50 m layer — and its bottom is the deepest model
    level within the server-side depth bound, which the chart's source line
    states rather than implies.
  - **Open-Meteo responses are cached for 10 minutes.** Its free tier
    rate-limits, and ten charts each refetching on every range change hits
    429 quickly; the 429 is also translated into a message that says what to
    do rather than leaking the raw client error.
  - **`status` on a KPI card is three-way** — `ready` / `warming` /
    `unavailable`. Cold-start and failure must not look alike: every cached
    service exposes `is_refreshing()` (derived from its existing refresh
    lock, no new state), and a warming card renders a progress bar animating
    against a measured typical duration rather than an error.

  Three frontend traps this feature already fell into, all fixed:
  - **Never key a Recharts axis on a formatted label.** `dataKey="label"`
    with "4 Aug" repeats yearly, so hover resolved to the first matching
    category and the crosshair cycled through year one forever. Use the raw
    timestamp and format via `tickFormatter`.
  - **Recharts' entry animation is off on these charts, deliberately.** It
    began before `ResponsiveContainer` settled its width, advanced its clip
    rect to ~12px of 646 and stalled there permanently — correct paths,
    clipped to invisible, under correct statistics.
  - **Do not rely on `IntersectionObserver` alone for lazy mounting.** In
    this app it was constructed and observing but never fired a callback at
    all, leaving every chart unmounted. `AnalyticsGrid`'s `LazyMount` now
    measures geometry directly on mount and on scroll, with the observer only
    as an extra trigger.


