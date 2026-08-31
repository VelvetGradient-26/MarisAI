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

## Getting started

### Prerequisites

- Node.js 20+
- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL — **optional.** Only chat-session history uses it; without a
  `DATABASE_URL` the assistant still works and simply cannot reopen past
  conversations.
- Docker + Docker Compose — only if using the Docker option below.

### Docker (fastest way to get running)

```bash
cp backend/.env.example backend/.env   # then fill in real credentials
docker compose up --build
```

Brings up Postgres, the backend (`http://localhost:8000`, migrations run
automatically on boot) and the frontend dev server (`http://localhost:5173`,
hot-reload via a bind mount) as one stack — no local Python/Node/Postgres
install required. `docker-compose.yml` and `backend/.env.example` at the repo
root have the full variable reference; `machine_learning/` still needs its own
venv (see below) since its output is only *read* by the backend, never run by
it. This is a dev stack, not a production deployment — the frontend serves via
Vite's dev server, not a built bundle.

### Backend (without Docker)

```bash
cd backend
uv sync
# create .env with the variables below
uv run uvicorn main:app --reload
```

Serves on `http://127.0.0.1:8000`. On boot it starts warming the global caches
in the background and serves everything else immediately; layers that depend on
a cold cache report themselves as warming until their first fetch lands.

`backend/.env` (see `backend/.env.example` for the full list):

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

### Frontend (without Docker)

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

- **Live observation layers** — SST, wind, currents, Stokes drift, a combined
  drift field, bathymetry, vessel density, marine boundaries; vector fields via
  a GPU particle engine (WebGL2). Exportable as a true ~4K PNG.
- **Mesoscale eddy detection and tracking** — Okubo-Weiss detection plus
  frame-to-frame tracking (Hungarian algorithm for ambiguous matches).
  Verified live at 100% continuity on 2,177 real detections; not yet validated
  against a reference atlas (AVISO+, account-gated).
- **Coastal upwelling and marine heatwave detection** — a Bakun wind-derived
  upwelling index, corroborated against an OISST-fitted climatology, reported
  as two separate claims.
- **eDNA sampling coverage** — where the ocean has been sampled molecularly,
  not a biodiversity layer. Coverage is a few hundredths of a percent, and the
  map states that rather than looking like a failed load.
- **A forecasting engine** (`backend/forecasting/`) — one framework for every
  variable. Adding a variable is a YAML block plus a training run. Global
  models regress on *change*, validated rolling-origin with an embargo; a
  horizon ships only if it beats persistence.
- **A forecast map** — the same engine as a global raster layer (`absolute` /
  `change` modes), or as a forecast particle field where two grids form a
  vector. Built offline, refreshed on a schedule.
- **Voyage planning and safety tools (conversational only)** — reached only
  through the assistant. Hazard-aware A* route planning, EEZ/boundary/MPA
  geofencing, a PFZ screening heuristic, GDACS cyclone alerts, and IMD CAP
  severe-weather alerts.
- **A point brief, and a comparison** — one coordinate as a document (screen or
  PDF), or two coordinates aligned row by row.
- **The Ocean Intelligence Dashboard** — global KPIs, live provider health,
  threshold-based alerts, and per-entity dossier pages (model / buoy /
  satellite product).
- **Universal Ocean Data Downloader** — 34 of 36 spec variables, 14 providers,
  correctly cadence-reconciled. Exports as CSV, JSON or PDF.
- **Offline ML** (`machine_learning/`) — HAB early warning and fish habitat /
  PFZ prediction, on a shared Marine Data Fusion Layer. Own environment, not
  imported by the backend; its exported grids are served as map layers.
- **An ocean assistant** — a bounded tool-calling loop (not RAG) over four
  delegated specialists (analytics, weather/safety, geospatial risk, web
  research) plus self-knowledge, with every answer checked against what the
  tools actually returned before it's shown as verified.

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
