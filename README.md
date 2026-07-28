# Maris AI

Maris AI is a marine intelligence platform that combines live oceanographic and
atmospheric data, satellite and vessel-tracking sources, and AI-generated
insights into a single interactive map. It renders sea surface temperature,
animated wind, bathymetry, vessel density, and marine boundary data over a
configurable set of basemaps, with point-and-click inspection of conditions at
any location on Earth.

## Overview

The platform is built as two independently deployable applications:

- **Frontend** (`frontend/`): a React + TypeScript single-page app built on
  MapLibre GL JS. All map behavior — basemaps, overlays, and controls — is
  driven by a config-driven layer registry rather than one-off components, so
  new data layers are added as declarative entries rather than new code paths.
- **Backend** (`backend/`): a FastAPI service that proxies and processes data
  from external providers (Copernicus Marine, Global Fishing Watch, GEBCO,
  Open-Meteo, NASA GIBS) so that credentials never reach the browser and raw
  scientific data formats (NetCDF, GRIB) never need to be handled client-side.

A separate `machine_learning/` component contains exploratory work on marine
habitat prediction and is not part of the deployed application.

## Features

- **Sea Surface Temperature** — rendered server-side from Copernicus Marine
  Service (`GLOBAL_ANALYSISFORECAST_PHY_001_024`), cached in memory and
  rasterized into map tiles with a smooth, perceptually continuous color
  ramp.
- **Animated wind** — a GPU particle system (WebGL2, transform feedback)
  driven by real Copernicus wind data (`WIND_GLO_PHY_L4_NRT_012_004`),
  rendering continuously flowing, speed-colored streamlines.
- **Bathymetry** — point depth-at-cursor lookups against the GEBCO global
  bathymetric grid.
- **Vessel density** — AIS and SAR-derived vessel presence heatmaps proxied
  from Global Fishing Watch's 4Wings API.
- **Marine boundaries** — Exclusive Economic Zones and Marine Protected Areas
  overlays.
- **Realtime marine and weather conditions** — wave height, currents, wind,
  and air temperature at any clicked location, with AI-generated summaries.
- **Dark Marine basemap** — a low-clutter, dark basemap purpose-built so data
  overlays read as the primary visual element.

Every layer is registered through a single configuration file
(`frontend/src/features/map/layers/layerRegistry.ts`); adding a new dataset is
a matter of adding an entry there rather than writing new rendering code.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, MapLibre GL JS 6, Zustand |
| Backend | FastAPI, SQLAlchemy (async), Alembic, httpx |
| Data processing | xarray, NumPy, SciPy, Pillow, copernicusmarine |
| Database | PostgreSQL |

## Getting started

### Prerequisites

- Node.js 20 or later
- Python 3.11
- PostgreSQL (for the backend database)
- [uv](https://docs.astral.sh/uv/) for Python dependency management
- Accounts/credentials for the external services listed below, as needed

### Backend

```bash
cd backend
uv sync
cp .env.example .env   # if present; otherwise create .env with the variables below
uv run uvicorn main:app --reload
```

The API serves on `http://127.0.0.1:8000` by default.

Required environment variables (`backend/.env`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `COPERNICUS_USERNAME` / `COPERNICUS_PASSWORD` | Copernicus Marine Service credentials (sea surface temperature and wind data) |
| `GFW_TOKEN` | Global Fishing Watch API token (vessel density layers) |
| `NASA_BEARER_TOKEN` | NASA Earthdata token (reserved for GIBS-authenticated layers) |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | AI insights provider configuration (Gemini, OpenAI-compatible, or Ollama) |

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The app serves on `http://localhost:5173` and proxies `/api` requests to the
backend at `http://127.0.0.1:8000` (see `frontend/vite.config.ts`).

Other frontend commands:

```bash
npm run build     # type-check (tsc -b) and produce a production build
npm run lint      # oxlint
npm run preview   # serve the production build locally
```

## Project structure

```
backend/
  main.py              FastAPI app entry point
  routers/              HTTP route definitions
  services/              External data integration and processing
  app/                  Database models, core config
frontend/
  src/features/map/       Map engine: managers, layers, basemaps, UI panels
    layers/                Layer registry and layer manager
    basemaps/               Basemap definitions
    vectorField/           Generic GPU particle engine (wind, and future
                            currents/waves)
machine_learning/       Exploratory marine habitat prediction work
Artifacts/              Design and data reference documents (not tracked)
```

## Data sources and attribution

This project uses only real, publicly documented data sources — no synthetic
or placeholder data is presented as live. Current sources include Copernicus
Marine Service, Global Fishing Watch, GEBCO, NASA EOSDIS GIBS, Open-Meteo,
Flanders Marine Institute (Marine Regions), and UNEP-WCMC/IUCN's World
Database on Protected Areas. Attribution for each dataset is shown in the
application's layer panel.
