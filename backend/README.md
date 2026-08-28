# MarisAI Backend

FastAPI. It exists so that credentials never reach the browser and NetCDF/GRIB
never need handling client-side, and it is where the forecasting engine runs
inference.

```bash
uv sync
# create .env — see the root README for the variable list
uv run uvicorn main:app --reload      # http://127.0.0.1:8000
uv run pytest tests/ -q
```

Dependencies are managed with `uv` (`pyproject.toml` + `uv.lock`). A generated
`requirements.txt` exists for non-uv installs; regenerate it rather than editing
it, and **regenerate it with `NO_COLOR=1`**:

```bash
NO_COLOR=1 uv export --format requirements.txt --no-hashes --no-dev > requirements.txt
```

Without it `uv export` writes ANSI colour escapes into the redirected file, and
the escape precedes the `#`, so every comment line stops being a comment. The
committed file once carried 322 such lines and `pip install -r requirements.txt`
failed on line 1. The corruption is invisible in an editor that renders colour,
and `uv` itself never reads the file, so nothing else catches it.

## Layout

```
main.py            App, middleware, scheduler wiring, cache warming
routers/           Thin HTTP layer — service errors mapped to status codes
services/          One self-contained module per integration or derived field
  chat/            The assistant: agent loop, tools, ledger, session store
  dashboard/       Cached global statistics, trends, alert rules
  download/        The universal downloader: registry, catalog, 14 providers
  metrics/          Per-variable metric pages, including the Ocean Story
forecasting/       The forecasting engine — see its own README.md
app/core/          Settings, logging, middleware
app/models/        SQLAlchemy schema (chat sessions are the live part)
models/            Trained artifacts, built grids, rejected horizons (not source)
scripts/           Offline training, grid builds, exports
alembic/           Migrations
tests/             ~30 suites; several of them exist to pin a decision, not a behaviour
```

## The four conventions

**1. Routers are thin.** A router catches a service-specific exception and maps
it to an `HTTPException` with a real status code. A raw provider exception or
traceback never reaches the client. Which code is chosen carries meaning:

- **502** — an upstream failed. `GET /api/ocean/biodiversity` blames OBIS.
- **503** — *our* cache is cold or unusable. `GET /api/ocean/eddies` reads a
  cache this server warms, so an unavailable answer is ours to explain.
- **422** — the caller got it wrong. Rejected *before* the service is called, so
  anything reaching the service's error handler is genuinely not the caller's
  fault.
- **404 that tells you how to fix it** — an untrained forecast model returns the
  training command, not a 500.

**2. Services are plain async functions and modules, not classes, not
DB-backed.** Each external integration is self-contained and carries its own
error type (`XError(RuntimeError)`): `copernicus_sst.py`, `copernicus_wind.py`,
`bathymetry.py`, `openmeteo.py`, `gfw.py`, `crw.py`, `feedback.py`,
`services/download/`. Derived fields follow the same shape — `drift.py`,
`eddies.py`, `brief.py`, `compare.py` compute from other services rather than
fetching.

**3. Cached, scheduled, never fetched per request.** A global field is tens of
megabytes per timestep and takes minutes to fetch. Every one of them is warmed
by an APScheduler job at a cadence matched to *the upstream product's own
publication rate* — hourly for wind and surface currents, 3-hourly for waves,
daily for depth-resolved currents — because refreshing faster than the product
publishes just refetches a field that cannot have changed. On failure a service
keeps its previous data. Boot warming is fire-and-forget: the app serves
immediately and a cold service reports itself **warming**, which is a distinct
answer from **failed**.

**4. Never substitute a number for missing data.** Every KPI, provider, section
and layer carries `available` plus an `unavailable_reason` that the interface
actually renders. Endpoints return 200 with per-item unavailability rather than
failing a whole page; only an unsatisfiable *request* is a 4xx. A fabricated
"0.00 mg/m³" is a false ocean reading, not a neutral placeholder.

## Does it need the database?

The schema is live and migrated, and **chat sessions are the reference
implementation** (`app/models/chat/session.py` + `services/chat/store.py`). The
`core`/`observations` schemas are migrated but unqueried. So the question for a
new feature is not "does this codebase use a database" — it does — but "does
this feature need *records*". An in-code registry (`services/download/registry.py`)
remains the default for **configuration**, which is what most of this backend
holds. Persistence is for things a user creates and expects back later.

`ChatSession.client_id` is the decision of record on scoping without auth:
authentication was removed (see `../docs/AUTH_REMOVAL.md`), and `client_id` is a
browser-generated UUID in localStorage that scopes a person's own history on
their own machine. Its docstring is explicit that this is **not** access
control. Reuse it rather than inventing a second answer — but a feature carrying
a *delivery target* (an email address, a webhook URL) raises a stake a
transcript does not, and needs confirmation and signed tokens on top.

Postgres is optional. Without `DATABASE_URL` the assistant works and simply
cannot reopen past conversations.

## Endpoints

| Prefix | What lives there |
|---|---|
| `/api/ocean` | Point and field values: SST, wind, currents (surface and at depth), Stokes drift, combined drift, bathymetry, biodiversity, **eddies**, drift presets. Field endpoints come in `.../field.png` + `.../meta` pairs feeding the GPU particle engine |
| `/api/tiles` | Raster tiles — SST, GFW vessel density |
| `/api/tiles/forecast` | The forecast map: scalar tiles, the vector-pair catalog, and `.../field.png` + `.../meta` for forecast particle fields |
| `/api/predictions` | Precomputed grids exported by `machine_learning/` — habitat, bloom risk |
| `/api/v1/forecast` | The forecasting engine (see `forecasting/README.md`) |
| `/api/v1/metrics` | One metric page per variable: series, statistics, Ocean Story |
| `/api/dashboard` | Global live state, alerts, trends, satellites, **data-quality** |
| `/api/brief` | One coordinate as a document, `/pdf`, and `/compare` |
| `/api/v1/chat` | The assistant — JSON and SSE, plus session history |
| `/api/v1` | Downloader (`/download`, `/variables`, `/ranges`, progress) and feedback |
| `/api/vessels` | Live AIS |
| `/api/insights` | LLM-generated commentary |

**`GET /api/dashboard/data-quality` is the answer to "what is actually
present"** — every dataset with grid spacing, cadence, coverage and licence;
every trained model with per-fold scores and a grade from the shipping rule; and
which variables have grids, which are pending, and which can never have one.
Prefer it to any count written in documentation, including this file's.

## Two things that will bite

**Copernicus Marine Toolbox has two zarr services with opposite chunking**, and
picking the wrong one for the access pattern turns a ~10 s fetch into
minutes or hours:

| Service | Chunking | Right for |
|---|---|---|
| `arco-geo-series` | Huge lat/lon chunks, one timestep each | Whole globe, latest snapshot (map tiles) — and whole globe, many timesteps (the forecast grid builder) |
| `arco-time-series` | Fine lat/lon chunks, huge time chunks | One bounded area, many timesteps (the downloader) |

Re-verify empirically — a real timed fetch — before assuming either fits a new
access pattern. Related: near-real-time products can publish empty (all-NaN)
trailing timesteps while being updated, so code that wants "the latest" must
walk backward and validate that data is present, not merely that the timestep
exists in the index (see `copernicus_wind.py::_fetch_latest_grid`).

**Blocking work goes in a worker thread, and must stay there.** The forecast
grid build is ~15 minutes of CPU with no `await` in it, and the scheduler starts
it on the event loop at boot; awaited inline it stalls *every* request on the
process for that window, presenting as a mysteriously dead API twice a day
rather than as an error. `ocean_state.py` and `copernicus_sst.py` follow the same
rule. New blocking work goes in the threaded span, new awaiting work in the
caller — and the test asserts on the *thread*, because a synthetic input builds
in milliseconds and any timing check would pass with the work back on the loop.

## Tests

`uv run pytest tests/ -q`. Several suites exist to pin a decision rather than a
behaviour, and are worth knowing about before "simplifying" one:

| Suite | What it protects |
|---|---|
| `test_vector_field.py` | Reimplements the shader's `fieldUV()` in Python and asserts the encoded texture decodes back to the velocity that went in. The encoder/shader contract crosses a language boundary and nothing type-checks it; every way it breaks is silent |
| `test_download_cadence.py` | Aggregation happens per provider *before* the merge, and derived codes resolve before aggregation. Both orderings were once wrong in ways that produced plausible numbers |
| `test_forecast_grid.py` | The grid path and the point path agree cell for cell, so optimising the cell loop is safe to attempt — and the cell loop stays off the event loop |
| `test_training_run_record.py` | `mlflow` never appears in `backend/`. The obvious later "improvement" is to log directly from the training script, which would invert a deliberate dependency direction |
| `test_forecasting.py` | Exactly one forward shift exists in the package, by scanning the source |
| `test_field_sampling.py` | Coverage is resampled separately from values, and the longitude wrap is measured rather than assumed |

## See also

- `forecasting/README.md` — the forecasting engine in full
- `../CLAUDE.md` (local, untracked) — the conventions, at length
- `../TODO.md` — pending work
- `../DONE.md` — what shipped, and the findings that outlived it
- `../docs/AUTH_REMOVAL.md` — why there is no authentication
