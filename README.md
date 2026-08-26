# Maris AI

A marine intelligence platform: live ocean and atmospheric data, an interactive
map, forecasting, offline ML, an analytics dashboard, a bulk data downloader,
and a grounded conversational assistant — all over real, publicly documented
sources.

**The rule the whole product is built around: never substitute a number for
missing data.** Every panel, KPI, provider and map layer carries an
availability flag and, when absent, a reason the interface actually renders. A
fabricated "0.00 mg/m³" is a false ocean reading, not a neutral placeholder. The
same discipline runs through the model output — predictions are labelled as
predictions, operating points are stated where they are weak, and the assistant
verifies that every figure in its answer came from a tool rather than from the
model.

## What it does

| Surface | Route | What it answers |
|---|---|---|
| Map | `/map` | What is happening, spatially — observations, forecasts, detections and model output as layers on a 3D globe |
| Ocean Intelligence Dashboard | `/dashboard` | What is happening globally, right now |
| Metric intelligence | `/dashboard/<variable>` | Everything known about one variable — history, forecast, drivers |
| Model dossier | `/dashboard/model` | Everything reproducible about one trained forecasting artifact |
| Point analytics | `/analytics` | Every metric at one coordinate |
| Compare | `/compare` | How one place differs from another |
| Assistant | `/assistant` | The whole platform through one conversational interface — including route planning, geofencing, and cyclone/weather alerts that have no other UI |
| Downloader | `/download` | Bulk export of 34 ocean variables as CSV/JSON/PDF |
| Docs | `/docs` | How everything here works, was built, validated, and where it fails — full-text searchable |

### The pieces

- **Live observation layers.** Sea surface temperature, wind, surface currents,
  Stokes drift, and a combined drift field (current + Stokes + wind leeway,
  selectable per object type), plus bathymetry, vessel density and marine
  boundaries. The vector fields are one GPU particle engine (WebGL2, transform
  feedback) over a texture encoded server-side. The current view — basemap plus
  whatever overlays are active — can be exported as a true ~4K PNG, a real
  higher-density re-render rather than an upscaled screenshot.
- **Mesoscale eddy detection and tracking.** Eddies are detected in the live
  surface-current field by the Okubo-Weiss method (position, size, polarity,
  intensity) and, separately, tracked frame to frame — nearest-neighbour
  matching within a polarity-separated, detector-jitter-sized gate, ambiguous
  clusters solved exactly via the Hungarian algorithm, tracks retired after two
  consecutive misses. Verified live on 2,177 real detections: matched through a
  synthetic jittered frame in 16 ms at 100% continuity. What tracking does
  *not* yet have is validation against a real reference: the per-frame
  detector's accuracy against AVISO+'s Mesoscale Eddy Trajectory Atlas is
  blocked on that dataset requiring a registered account, and the tracker's own
  matcher is presently unit-tested on synthetic data only.
- **Coastal upwelling and marine heatwave detection.** A Bakun wind-derived
  upwelling index, corroborated by whether the water is actually cool against
  an OISST-fitted climatology — two separate claims, reported separately,
  including a control showing the correlation is real but weak. A parallel
  attempt to fit that climatology against Copernicus reanalysis instead (to cut
  OISST's multi-day lag) was built, measured, and shelved: it did not improve
  the corroboration signal and is deliberately not wired into the live path.
- **eDNA sampling coverage.** Where the ocean has been sampled *molecularly* —
  not a biodiversity layer. Measured live: eDNA records cover a few hundredths
  of a percent of the ocean at a meaningful grid resolution, so the map is
  mostly blank on purpose, and that blankness is stated rather than left to
  read as a failed load.
- **A forecasting engine** (`backend/forecasting/`) — one framework for *every*
  variable rather than one model per variable. Adding a variable is a YAML block
  naming a code the download registry already serves, plus a training run; the
  metric-intelligence page for it then exists with no frontend change. Models
  are global (one per variable+horizon across configured points, with
  lat/lon/depth/basin as features), regress on the *change* rather than the
  level, and are validated rolling-origin with an embargo — never a random
  split. A horizon ships only if it beats persistence **and** at most one of
  five folds is negative.
- **A forecast map.** The same engine rendered as a global raster layer, in
  `absolute` and `change` modes — `change` (forecast minus the latest
  observation) being the informative one, since the absolute field at +7d looks
  almost exactly like today's. Where two grids hold the components of one
  vector, they compose into a forecast *particle* field instead, drawn exactly
  like its live counterpart so the two can be compared. Grids are built offline
  and refreshed on a schedule.
- **Voyage planning and safety tools — conversational only.** Reached
  exclusively through the assistant; none of these has a REST endpoint or map
  layer of its own. Hazard-aware route planning does an A* search over a live
  grid that excludes land, the India–Sri Lanka maritime boundary and marine
  protected areas outright, weighting the remaining edges by live wave height.
  Geofencing checks a point against India's EEZ (mainland plus Andaman &
  Nicobar), that same boundary line, and a curated protected-area list, using
  real geometry from Marine Regions rather than hand-sketched polygons.
  Potential-fishing-zone screening is an explicit heuristic (above-median
  chlorophyll in a 24–30°C band) — stated as a screening aid, not the validated
  model INCOIS ships, and independent of the trained fish-habitat model below.
  Cyclone alerts come from GDACS (since India's IMD publishes no machine-
  readable track feed); severe weather alerts come from IMD's own CAP feed —
  and are a genuinely different signal, verified against five real cyclone
  landfalls that IMD's feed reported only as "Heavy Rain," never "Cyclone."
- **A point brief, and a comparison.** One coordinate rendered as a document
  (on screen or as a PDF), and two coordinates aligned row by row. Both are
  composition rather than computation — every number already has an endpoint —
  and a row only one point has is kept and labelled rather than dropped, because
  the asymmetry is often the most informative part.
- **The Ocean Intelligence Dashboard.** Global KPIs, live provider health, and
  threshold-based alerts that state their own basis rather than reading as an
  issued warning — plus per-entity dossier pages (one trained model, one NDBC
  buoy, one satellite product) reached by clicking through, not a separate
  section to navigate to. Every KPI and provider distinguishes "still warming
  up" from "unavailable" rather than looking alike.
- **Universal Ocean Data Downloader.** 34 of 36 spec variables against real
  data, across 14 providers with independently varying cadence and grid
  spacing, reconciled correctly (aggregate before merge, not after) rather than
  silently mixing an hourly field's instantaneous sample where a daily mean
  belongs. Exports as CSV, JSON or PDF.
- **Offline ML** (`machine_learning/`) — harmful algal bloom early warning and
  fish habitat / potential fishing zones, on a shared Marine Data Fusion Layer.
  It has its own environment and is **not imported by the backend**; its
  exported prediction grids are served as map layers, so it is part of the
  running product even though the import boundary holds.
- **An ocean assistant** — a bounded tool-calling loop over the platform's own
  services, not RAG. The top-level model holds five tools: four
  `delegate_to_*` specialists (`ocean_analytics` for forecasts/HAB/habitat/PFZ,
  `weather_safety` for live conditions/cyclones/IMD alerts, `geospatial_risk`
  for geofencing/depth/routing, `web_research` for web search/webpage
  reading/scientific literature — context beyond MarisAI's own live data)
  plus a self-knowledge tool bound directly, since documentation lookup isn't
  a live measurement the way the specialists' work is. Each specialist runs
  its own bounded sub-loop over a shared ledger, which is also what the
  grounding check reads. Streaming (SSE) and non-streaming endpoints share
  one loop, and every answer is checked against what the tools actually
  returned before it's shown as verified.

## Architecture

Three applications, deliberately separated:

- **`frontend/`** — React 19 + TypeScript + Vite + MapLibre GL JS 6 + Zustand.
  Map behaviour is driven by a layer registry rather than one-off components.
- **`backend/`** — FastAPI. It proxies and processes external data so
  credentials never reach the browser and NetCDF/GRIB never need handling
  client-side. It is also where the forecasting engine runs inference.
- **`machine_learning/`** — offline pipelines with their own `uv` environment.
  See its `README.md`.

Two boundaries are load-bearing and easy to erode:

- **The backend never imports `machine_learning`.** It reads exported grids.
  The forecasting engine is the one place the backend carries a modelling
  dependency, because it answers arbitrary (variable, point, horizon) queries
  that no offline export could enumerate.
- **Cached, scheduled, never fetched per request.** Global fields are tens of
  megabytes per timestep and take minutes to fetch; every one of them is warmed
  by a scheduler and served from memory. A cold cache reports itself as warming
  — distinct from failed. The one exception by design is the voyage-planning
  chat tools (geofencing, routing, PFZ, cyclones, severe weather), which are
  either pure local computation or backed by their own short-lived in-memory
  caches rather than the scheduler.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, MapLibre GL JS 6, Zustand, framer-motion |
| Dashboard (scoped exception) | Tailwind v4, React Query, Recharts, uPlot |
| Assistant | `@assistant-ui/react` headless primitives |
| Backend | FastAPI, httpx, loguru, APScheduler, SQLAlchemy (async) + Alembic |
| Data processing | xarray, NumPy, SciPy, Shapely, Pillow, copernicusmarine |
| Modelling | LightGBM, SHAP, scikit-learn; MLflow for experiment tracking |
| Database | PostgreSQL — used for chat sessions only, and optional |

Outside `features/dashboard/` and `features/assistant/` the frontend is
hand-rolled: no UI kit, no CSS framework, no form or date-picker library. That
is a convention, not an accident — match it rather than adding a dependency for
one component.

## Getting started

### Prerequisites

- Node.js 20+
- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL — **optional.** Only chat-session history uses it; without a
  `DATABASE_URL` the assistant still works and simply cannot reopen past
  conversations.

### Backend

```bash
cd backend
uv sync
# create .env with the variables below
uv run uvicorn main:app --reload
```

Serves on `http://127.0.0.1:8000`. On boot it starts warming the global caches
in the background and serves everything else immediately; layers that depend on
a cold cache report themselves as warming until their first fetch lands.

`backend/.env`:

| Variable | Purpose |
|---|---|
| `COPERNICUS_USERNAME` / `COPERNICUS_PASSWORD` | Copernicus Marine — SST, wind, currents, waves, biogeochemistry. The one credential most of the product needs |
| `GFW_TOKEN` | Global Fishing Watch (vessel density) |
| `AISSTREAM_API_KEY` | Live AIS websocket feed. Without it the vessel layer serves an empty collection rather than failing |
| `NASA_BEARER_TOKEN` | NASA Earthdata (GIBS-authenticated layers) |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | Assistant and insights provider (Gemini, OpenAI-compatible, or Ollama) |
| `TAVILY_API_KEY` | The Ocean Assistant's `web_research` specialist (web search). Without it, `web_search` reports itself unavailable rather than failing the assistant; `fetch_webpage` and `search_scientific_literature` need no key |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Gmail app password, for the feedback form |
| `DATABASE_URL` | PostgreSQL. Optional — see above |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` by default; `LOG_JSON=true` emits one JSON object per line |
| `FORECAST_GRID_REFRESH_ON_BOOT` | Set `false` on a small machine — a rebuild peaks around 3 GB per variable |

No key is needed for the voyage-planning chat tools: GDACS, IMD's CAP feed and
Marine Regions' WFS are all unauthenticated reads. Never commit real values;
`backend/.env` is untracked.

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to the backend
npm run build      # tsc -b + production build
npm run lint       # oxlint
```

### Tests

```bash
cd backend && uv run pytest tests/ -q

# machine_learning/ has its own venv and requirements.txt — no pyproject,
# so it is not a `uv run` project.
cd machine_learning && .venv/bin/pytest        # leakage and methodology guards
```

The machine-learning suite is worth running deliberately: it enforces "only one
forward shift exists", "never random K-fold", and "climatology fitted on
training rows only" — the guardrails against silent methodology error.

## Offline pipelines

```bash
cd backend
uv run python scripts/train_forecasting.py --variable sea_surface_temperature
uv run python scripts/apply_shipping_bar.py --dry-run
uv run python scripts/build_forecast_grid.py --all --skip-fresh 24
```

Training and grid building are offline only — never triggered by a request. A
grid build is dominated by the upstream fetch and is largely independent of
output resolution, so budget for it.

The middle step is not optional bookkeeping. A horizon ships only if it beats
persistence **and** at most one of five folds is negative, and the trainer has
no concept of rejection — it trains every configured horizon and saves each one
that fits, so a batch retrain silently resurrects horizons that were deleted on
their own merits. `apply_shipping_bar.py` re-applies the rule and *moves*
failures to `models/forecasting/_rejected/<date>/` rather than deleting them,
because the artifact is the evidence for the decision.

`GET /api/dashboard/data-quality` reports what is actually present: every
dataset with its grid spacing, cadence, coverage and licence; every trained
model with its per-fold scores and a grade computed from the shipping rule; and
which variables have grids, which are pending, and which can never have one.
Prefer it to any count written in documentation.

## Project structure

```
backend/
  main.py               FastAPI app; scheduler wiring and cache warming
  routers/               Thin HTTP layer — maps service errors to status codes
  services/              One self-contained module per integration or derived field
    chat/                orchestrator.py + specialists.py (4 delegated agents), tools.py
    climatology/         OISST (live) and Copernicus reanalysis (measured, unwired)
    geofencing.py, routing.py, pfz.py, cyclones.py, severe_weather.py,
    web_search.py, webpage.py, literature.py
                          Chat-only tools — no REST router of their own
    eddy_tracking.py      Frame-to-frame tracking over eddies.py's detections
  forecasting/           The forecasting engine (config-driven, one framework)
  app/core/               Settings, logging, middleware
  app/models/            SQLAlchemy schema (chat sessions are the live part)
  models/                Trained artifacts and built grids (not source)
  scripts/               Offline training, grid builds, exports, validation
frontend/src/
  features/map/           Map engine: managers, layer registry, GPU vector fields
  features/dashboard/      Ocean Intelligence Dashboard, metric pages, dossiers
  features/assistant/      Chat thread
  pages/                  Hand-rolled pages (landing, download, compare, docs, …)
    docs/                  Chapters + DocsSearch.tsx (full-text, evaluates chapter
                           components directly rather than reading static text)
machine_learning/
  marine_ml/              Shared spine: ingestion, fusion, features, validation
  hab_early_warning/      Bloom risk
  fish_habitat_prediction/  Habitat suitability / PFZ (the validated model —
                           independent of the assistant's PFZ heuristic above)
research/               Papers, reproducible notebooks and exported datasets
```

## Research

`research/` holds work written *from* this codebase rather than about it. The
shipped paper — "Rising Skill, Falling Skill" — argues that persistence alone is
an insufficient baseline for statistical ocean forecasting, using the
forecasting engine's own training data: 13 variables × 4 horizons, plus 1,248
held-out fits. Persistence error grows with horizon and a seasonal cycle's does
not, so a persistence-referenced score can rise while the model degrades. Median
skill against persistence is +0.273 at 30 days; against a day-of-year
climatology it is −0.023.

It is also the place a retraction is recorded. An earlier draft concluded those
models had "learned what month it is"; a three-arm feature ablation showed 10 of
the 11 affected cases keep their skill with every calendar feature removed, so
losing to climatology reports the *baseline's* strength rather than the model's
mechanism. `research/research.md` catalogues the other papers this repository
already holds the artefacts for, and how far each one is from being writable —
including two recent negative results kept for the same reason: fitting
upwelling's SST-corroboration climatology against Copernicus reanalysis instead
of OISST measurably failed to help, and eddy detection's accuracy against a real
reference atlas (AVISO+) remains unmeasured because that dataset requires
registered access.

## Data sources and attribution

Only real, publicly documented sources — nothing synthetic is ever presented as
live. Copernicus Marine Service, NOAA Coral Reef Watch, NOAA NDBC, GEBCO (via
Ifremer ERDDAP), Open-Meteo, NASA EOSDIS GIBS, Global Fishing Watch, OBIS,
GDACS, India Meteorological Department (public CAP feed), Flanders Marine
Institute (Marine Regions), and UNEP-WCMC/IUCN's World Database on Protected
Areas. Per-dataset attribution — including product identifiers, grid spacing
and cadence — is shown in the application's layer panel and served by
`/api/dashboard/data-quality`.

## Contributing

`CLAUDE.md` (untracked, local) carries the conventions. `TODO.md` holds pending
work only; `DONE.md` holds what shipped, together with the finding that outlived
it — a measured number, or a decision with its reason attached.

**`DONE.md` is the more useful of the two to read first.** It is not a
changelog: it is the record of what was already tried, measured and rejected,
including several beliefs this project held confidently and had to correct. A
good deal of it exists so the same ground is not covered twice.
