import asyncio
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import settings
from forecasting.api import router as forecasting_router
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
    forecast_tiles,
    forecast_warm,
    gibs,
    ndbc,
    ocean_state,
)
from services.copernicus_currents import refresh_currents_cache
from services.copernicus_sst import refresh_sst_cache
from services.copernicus_wind import refresh_wind_cache

SST_REFRESH_INTERVAL_HOURS = 3
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
    asyncio.create_task(refresh_wind_cache())
    asyncio.create_task(refresh_currents_cache())

    # The dashboard's caches, on the same fire-and-forget footing. Each
    # service keeps its previous data on a failed refresh and reports itself
    # unavailable until its first success, so a slow or broken upstream costs
    # one widget rather than startup. The ocean-state snapshot is the slow
    # one (~80s for five global fields) and is deliberately not awaited.
    asyncio.create_task(ndbc.refresh_cache())
    asyncio.create_task(crw.refresh_cache())
    asyncio.create_task(gibs.refresh_cache())
    asyncio.create_task(ocean_state.refresh_cache())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(refresh_sst_cache, "interval", hours=SST_REFRESH_INTERVAL_HOURS)
    scheduler.add_job(refresh_wind_cache, "interval", hours=WIND_REFRESH_INTERVAL_HOURS)
    scheduler.add_job(
        refresh_currents_cache, "interval", hours=CURRENTS_REFRESH_INTERVAL_HOURS
    )
    scheduler.add_job(
        ndbc.refresh_cache, "interval", minutes=ndbc.REFRESH_INTERVAL_MINUTES
    )
    scheduler.add_job(crw.refresh_cache, "interval", hours=crw.REFRESH_INTERVAL_HOURS)
    scheduler.add_job(gibs.refresh_cache, "interval", hours=gibs.REFRESH_INTERVAL_HOURS)
    scheduler.add_job(
        ocean_state.refresh_cache, "interval", hours=ocean_state.REFRESH_INTERVAL_HOURS
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
