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
| Map | `/map` | What is happening, spatially — observations, forecasts and model output as layers on a 3D globe |
| Ocean Intelligence Dashboard | `/dashboard` | What is happening globally, right now |
| Metric intelligence | `/dashboard/<variable>` | Everything known about one variable — history, forecast, drivers |
| Point analytics | `/analytics` | Every metric at one coordinate |
| Compare | `/compare` | How one place differs from another |
| Assistant | `/assistant` | The whole platform through one conversational interface |
| Downloader | `/download` | Bulk export of 34 ocean variables as CSV/JSON/PDF |
| Docs | `/docs` | How the models were built, validated, and where they fail |

### The pieces

- **Live observation layers.** Sea surface temperature, wind, surface currents,
  Stokes drift, currents at six depth levels, and a combined drift field
  (current + Stokes + wind leeway), plus bathymetry, vessel density and marine
  boundaries. The vector fields are one GPU particle engine (WebGL2, transform
  feedback) over a texture encoded server-side.
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
  `absolute` and `change` modes. Grids are built offline and refreshed on a
  schedule.
- **Offline ML** (`machine_learning/`) — harmful algal bloom early warning and
  fish habitat / potential fishing zones, on a shared Marine Data Fusion Layer.
  It has its own environment and is **not imported by the backend**; its
  exported prediction grids are served as map layers, so it is part of the
  running product even though the import boundary holds.
- **An ocean assistant** — a bounded tool-calling loop over the platform's own
  services, not RAG. Streaming (SSE) and non-streaming endpoints share one loop,
  and every answer is checked against what the tools actually returned.

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
  — distinct from failed.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, MapLibre GL JS 6, Zustand, framer-motion |
| Dashboard (scoped exception) | Tailwind v4, React Query, Recharts, uPlot |
| Assistant | `@assistant-ui/react` headless primitives |
| Backend | FastAPI, httpx, loguru, APScheduler, SQLAlchemy (async) + Alembic |
| Data processing | xarray, NumPy, SciPy, Pillow, copernicusmarine |
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
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Gmail app password, for the feedback form |
| `DATABASE_URL` | PostgreSQL. Optional — see above |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` by default; `LOG_JSON=true` emits one JSON object per line |
| `FORECAST_GRID_REFRESH_ON_BOOT` | Set `false` on a small machine — a rebuild peaks around 3 GB per variable |

Never commit real values; `backend/.env` is untracked.

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
uv run python scripts/build_forecast_grid.py --all --skip-fresh 24
```

Training and grid building are offline only — never triggered by a request. A
grid build is dominated by the upstream fetch and is largely independent of
output resolution, so budget for it.

`GET /api/dashboard/data-quality` reports what is actually present: every
dataset with its grid spacing, cadence, coverage and licence; every trained
model with its per-fold scores and a grade computed from the shipping rule; and
which variables have grids, which are pending, and which can never have one.
Prefer it to any count written in documentation.

## Project structure

```
backend/
  main.py               FastAPI app; scheduler wiring and cache warming
  routers/              Thin HTTP layer — maps service errors to status codes
  services/             One self-contained module per integration or derived field
  forecasting/          The forecasting engine (config-driven, one framework)
  app/core/             Settings, logging, middleware
  app/models/           SQLAlchemy schema (chat sessions are the live part)
  models/               Trained artifacts and built grids (not source)
  scripts/              Offline training, grid builds, exports
frontend/src/
  features/map/         Map engine: managers, layer registry, GPU vector fields
  features/dashboard/   Ocean Intelligence Dashboard and metric pages
  features/assistant/   Chat thread
  pages/                Hand-rolled pages (landing, download, compare, docs, …)
machine_learning/
  marine_ml/            Shared spine: ingestion, fusion, features, validation
  hab_early_warning/    Bloom risk
  fish_habitat_prediction/  Habitat suitability / PFZ
```

## Data sources and attribution

Only real, publicly documented sources — nothing synthetic is ever presented as
live. Copernicus Marine Service, NOAA Coral Reef Watch, NOAA NDBC, GEBCO (via
Ifremer ERDDAP), Open-Meteo, NASA EOSDIS GIBS, Global Fishing Watch, OBIS,
Flanders Marine Institute (Marine Regions), and UNEP-WCMC/IUCN's World Database
on Protected Areas. Per-dataset attribution — including product identifiers,
grid spacing and cadence — is shown in the application's layer panel and served
by `/api/dashboard/data-quality`.

## Contributing

`CLAUDE.md` (untracked, local) and `TODO.md` carry the conventions and the open
work. `TODO.md` is the more useful of the two to read first: items are removed
when they ship, and what stays behind is the measured finding or the decision
with its reason — so it doubles as a record of what has already been tried and
why it was rejected.
