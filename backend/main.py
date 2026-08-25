import asyncio
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.s3_pool import widen_s3_connection_pool

# Before copernicusmarine builds its first S3 client, which it does lazily on
# the first dataset open. See app/core/s3_pool.py for why the default of 10 is
# wrong for a zarr read and why the fix has to be a botocore default.
widen_s3_connection_pool()

# Before any other import that logs. Most of this backend's log calls go through
# stdlib `logging`, which nothing configured until now — see app/core/logging.py
# for what that cost. Calling it at import rather than in `lifespan` is
# deliberate: module-level code in the routers below logs during import, and a
# lifespan hook runs far too late to catch it.
configure_logging(level=settings.LOG_LEVEL, json_logs=settings.LOG_JSON)

from forecasting.api import router as forecasting_router
from routers.brief import router as brief_router
from routers.chat import router as chat_router
from routers.dashboard import router as dashboard_router
from routers.download import router as download_router
from routers.feedback import router as feedback_router
from routers.forecast_tiles import router as forecast_tiles_router
from routers.insights import router as insights_router
from routers.marine import router as marine_router
from routers.metrics import router as metrics_router
from routers.predictions import router as predictions_router
from routers.tiles import router as tiles_router
from routers.vessels import router as vessels_router
from services import (
    ais,
    crw,
    currents_depth,
    drift,
    eddy_tracking,
    forecast_tiles,
    forecast_warm,
    gibs,
    heatwaves,
    ndbc,
    ocean_state,
    stokes_drift,
)
from services.copernicus_chlorophyll import refresh_chlorophyll_cache
from services.copernicus_currents import refresh_currents_cache
from services.copernicus_sst import refresh_sst_cache
from services.copernicus_wind import refresh_wind_cache

SST_REFRESH_INTERVAL_HOURS = 3
# The BGC-PFT product this feeds is daily, so anything faster re-fetches a
# field that cannot have changed — same reasoning as heatwaves' OISST cadence.
CHLOROPHYLL_REFRESH_INTERVAL_HOURS = 12
# Wind's source dataset is itself hourly (vs. SST's underlying hourly-but-slow-
# changing thetao) and drives a live animation, so it's refreshed more often.
WIND_REFRESH_INTERVAL_HOURS = 1
# Currents come from the same hourly product as SST and drive an animation like
# wind's, so they follow wind's cadence rather than SST's — the layer's whole
# point is that it is moving *now*.
CURRENTS_REFRESH_INTERVAL_HOURS = 1


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Kick off in the background rather than awaiting: the initial fetch
    # takes ~10-30s (a full global grid), and the app should start serving
    # other routes immediately rather than blocking boot on it. Until it
    # finishes, SST/wind endpoints report "not yet available" (see
    # CopernicusSstError/CopernicusWindError) instead of erroring.
    asyncio.create_task(refresh_sst_cache())
    # Feeds the PFZ ("nearest fishing zone") chat tool, on the same
    # fire-and-forget footing as everything else here.
    asyncio.create_task(refresh_chlorophyll_cache())
    # Wind, surface currents and Stokes drift warm together and then compose the
    # combined drift field, which is summed from all three. Gathered rather than
    # created separately so the compose can be chained onto them: it needs every
    # term present, and the alternative — a scheduled compose that finds a cold
    # cache — leaves the drift layer unavailable for a full interval after boot
    # for no reason. The three still fetch concurrently, exactly as before.
    async def _warm_flow_fields() -> None:
        await asyncio.gather(
            refresh_wind_cache(), refresh_currents_cache(), stokes_drift.refresh_cache()
        )
        await drift.refresh_cache()

    asyncio.create_task(_warm_flow_fields())
    # The depth-resolved currents, on the same fire-and-forget footing. Depth
    # warms only the levels someone has opened (plus two on the schedule) — six
    # whole-globe fetches per cycle for levels nobody is looking at is most of
    # the cost of the feature for none of its value.
    asyncio.create_task(currents_depth.refresh_cache())

    # The dashboard's caches, on the same fire-and-forget footing. Each
    # service keeps its previous data on a failed refresh and reports itself
    # unavailable until its first success, so a slow or broken upstream costs
    # one widget rather than startup. The ocean-state snapshot is the slow
    # one (~80s for five global fields) and is deliberately not awaited.
    asyncio.create_task(ndbc.refresh_cache())
    asyncio.create_task(crw.refresh_cache())
    asyncio.create_task(gibs.refresh_cache())
    asyncio.create_task(ocean_state.refresh_cache())
    # Marine heatwaves. Cheap (one griddap request plus a numpy pass) and it
    # degrades to a logged note when no climatology has been built yet, so a
    # fresh clone starts without it rather than failing.
    asyncio.create_task(heatwaves.refresh_cache())
    # Eddy tracking's first tick, same fire-and-forget footing as the rest of
    # this block. It reads the currents cache `_warm_flow_fields` is warming
    # concurrently above, so on a cold boot this can race it and find nothing
    # yet — `eddy_tracking.refresh()` degrades to a logged skip in exactly
    # that case (see its own docstring), and the scheduled job below picks it
    # up on the next hourly tick regardless. A single frame does not track
    # anything by itself either way; what matters is that the *next* refresh
    # has a first frame already on record to match against.
    asyncio.create_task(eddy_tracking.refresh())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(refresh_sst_cache, "interval", hours=SST_REFRESH_INTERVAL_HOURS)
    scheduler.add_job(
        refresh_chlorophyll_cache, "interval", hours=CHLOROPHYLL_REFRESH_INTERVAL_HOURS
    )
    scheduler.add_job(refresh_wind_cache, "interval", hours=WIND_REFRESH_INTERVAL_HOURS)
    scheduler.add_job(
        refresh_currents_cache, "interval", hours=CURRENTS_REFRESH_INTERVAL_HOURS
    )
    # Same cadence as the currents cache it reads: eddy positions barely move
    # inside an hour (a few km/day for a real mesoscale eddy), so anything
    # faster would just re-process a snapshot `update()` has already seen
    # (it is idempotent on a repeated timestamp) for no new information.
    scheduler.add_job(
        eddy_tracking.refresh, "interval", hours=CURRENTS_REFRESH_INTERVAL_HOURS
    )
    # Cadences match each product's own publication rate rather than a shared
    # default: the wave product is 3-hourly and the depth currents daily, so a
    # faster interval would refetch a field that cannot have changed.
    scheduler.add_job(
        stokes_drift.refresh_cache, "interval", hours=stokes_drift.REFRESH_INTERVAL_HOURS
    )
    scheduler.add_job(
        currents_depth.refresh_cache, "interval", hours=currents_depth.REFRESH_INTERVAL_HOURS
    )
    # The combined drift field recomposes from the three caches above rather
    # than fetching anything, so it is cheap and matched to the fastest of them.
    # Slightly offset from the hour by running on its own interval: composing
    # while a term is mid-refresh is harmless (it reads whatever is cached) and
    # the next cycle picks the new timestep up.
    scheduler.add_job(
        drift.refresh_cache, "interval", hours=drift.REFRESH_INTERVAL_HOURS
    )
    scheduler.add_job(
        ndbc.refresh_cache, "interval", minutes=ndbc.REFRESH_INTERVAL_MINUTES
    )
    scheduler.add_job(crw.refresh_cache, "interval", hours=crw.REFRESH_INTERVAL_HOURS)
    scheduler.add_job(gibs.refresh_cache, "interval", hours=gibs.REFRESH_INTERVAL_HOURS)
    scheduler.add_job(
        ocean_state.refresh_cache, "interval", hours=ocean_state.REFRESH_INTERVAL_HOURS
    )
    # OISST is a daily product published with about a day's lag, so anything
    # faster re-fetches a field that cannot have changed.
    scheduler.add_job(
        heatwaves.refresh_cache, "interval", hours=heatwaves.REFRESH_INTERVAL_HOURS
    )
    # The forecast map's grids. By far the most expensive job here — ~25 min of
    # Copernicus reads and feature building per variable — so it runs twice a
    # day and skips any grid already newer than that interval. That skip is
    # what makes the boot-time call safe: a restart re-checks freshness rather
    # than rebuilding, and a machine with no grid at all starts producing one
    # instead of waiting twelve hours for the first tick.
    if settings.FORECAST_GRID_REFRESH_ON_BOOT:
        asyncio.create_task(forecast_tiles.refresh_grids())
    else:
        logger.info(
            "forecast grid rebuild on boot disabled "
            "(FORECAST_GRID_REFRESH_ON_BOOT=false); the scheduled job still runs"
        )
    scheduler.add_job(
        forecast_tiles.refresh_grids,
        "interval",
        hours=forecast_tiles.REFRESH_INTERVAL_HOURS,
    )
    # Fill the point-forecast history cache before anyone asks for it. A cold
    # metric page costs ~33s, warm ~0.08s, and the whole difference is the
    # upstream fetch this sweep pays for. It is fire-and-forget for the same
    # reason as everything above it: until it finishes, pages are merely as
    # slow as they were before, which is not a reason to delay boot.
    asyncio.create_task(forecast_warm.refresh_cache())
    scheduler.add_job(
        forecast_warm.refresh_cache,
        "interval",
        hours=forecast_warm.REFRESH_INTERVAL_HOURS,
    )
    scheduler.start()

    # Long-lived websocket to aisstream.io. Self-supervising and a no-op
    # without an API key, so it never blocks or breaks startup.
    ais.start()

    yield

    scheduler.shutdown(wait=False)
    await ais.stop()


app = FastAPI(title="MarisAI Backend", lifespan=lifespan)

# Registered before CORS, which — verified, not assumed — puts CORS *outside*
# this: Starlette's `add_middleware` inserts at the head of the list and the
# stack is built in reverse, so the last one added ends up outermost.
#
# That is the order we want. A CORS preflight is answered by CORSMiddleware
# without ever reaching here, so OPTIONS requests produce no access line and
# consume no request id, while every real request still passes through.
app.add_middleware(RequestContextMiddleware)

# An explicit origin list, not ["*"]. `allow_credentials` is kept on despite
# session cookies having gone with authentication (see docs/AUTH_REMOVAL.md),
# because a browser rejects a wildcard origin whenever it is set — turning it
# off would let the list silently become decorative if credentials are ever
# reintroduced. Configure via CORS_ORIGINS in .env. Mostly moot in dev, where
# Vite proxies /api and requests are same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(marine_router)
app.include_router(insights_router)
app.include_router(tiles_router)
app.include_router(download_router)
app.include_router(feedback_router)
app.include_router(predictions_router)
app.include_router(forecast_tiles_router)
app.include_router(chat_router)
app.include_router(vessels_router)
app.include_router(dashboard_router)
app.include_router(brief_router)
# Serves precomputed models from `models/forecasting/`. Nothing is trained at
# request time and nothing is scheduled — an untrained variable answers 404
# with the command to train it, so mounting this is safe on a cold install.
app.include_router(forecasting_router)
# Descriptive analytics for the metric intelligence pages. Reads the same
# history as the forecasting engine, so a page's chart and its forecast can
# never disagree about what the record says.
app.include_router(metrics_router)


@app.get("/")
def healthcheck():
    return {"status": "ok"}
