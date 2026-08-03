import asyncio
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.config import settings
from app.database.mongo import MongoUnavailableError, close_mongo, ensure_indexes
from routers.auth import router as auth_router
from routers.download import router as download_router
from routers.feedback import router as feedback_router
from routers.insights import router as insights_router
from routers.marine import router as marine_router
from routers.predictions import router as predictions_router
from routers.saved_locations import router as saved_locations_router
from routers.tiles import router as tiles_router
from routers.vessels import router as vessels_router
from services import ais
from services.copernicus_sst import refresh_sst_cache
from services.copernicus_wind import refresh_wind_cache

SST_REFRESH_INTERVAL_HOURS = 3
# Wind's source dataset is itself hourly (vs. SST's underlying hourly-but-slow-
# changing thetao) and drives a live animation, so it's refreshed more often.
WIND_REFRESH_INTERVAL_HOURS = 1


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Kick off in the background rather than awaiting: the initial fetch
    # takes ~10-30s (a full global grid), and the app should start serving
    # other routes immediately rather than blocking boot on it. Until it
    # finishes, SST/wind endpoints report "not yet available" (see
    # CopernicusSstError/CopernicusWindError) instead of erroring.
    asyncio.create_task(refresh_sst_cache())
    asyncio.create_task(refresh_wind_cache())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(refresh_sst_cache, "interval", hours=SST_REFRESH_INTERVAL_HOURS)
    scheduler.add_job(refresh_wind_cache, "interval", hours=WIND_REFRESH_INTERVAL_HOURS)
    scheduler.start()

    # Long-lived websocket to aisstream.io. Self-supervising and a no-op
    # without an API key, so it never blocks or breaks startup.
    ais.start()

    # Idempotent. Deliberately non-fatal: an unreachable Atlas cluster should
    # cost you sign-in, not the whole map/tiles/download surface, which needs
    # no database at all.
    try:
        await ensure_indexes()
    except MongoUnavailableError as exc:
        logger.warning(f"MongoDB not configured — sign-in will be unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001 - startup must survive a bad cluster
        logger.warning(f"Could not reach MongoDB, sign-in will be unavailable: {exc}")

    yield

    scheduler.shutdown(wait=False)
    await ais.stop()
    await close_mongo()


app = FastAPI(title="MarisAI Backend", lifespan=lifespan)

# An explicit origin list, not ["*"]: browsers reject a wildcard origin when
# allow_credentials=True, which would stop the session cookie from ever being
# sent. Configure via CORS_ORIGINS in .env. Mostly moot in dev, where Vite
# proxies /api and requests are same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MongoUnavailableError)
async def _mongo_unavailable_handler(_request: Request, exc: MongoUnavailableError):
    """Unconfigured/unreachable Mongo is a 503, not a 500 with a pymongo
    traceback — same posture as every service-specific error in this codebase."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.include_router(marine_router)
app.include_router(auth_router)
app.include_router(saved_locations_router)
app.include_router(insights_router)
app.include_router(tiles_router)
app.include_router(download_router)
app.include_router(feedback_router)
app.include_router(predictions_router)
app.include_router(vessels_router)


@app.get("/")
def healthcheck():
    return {"status": "ok"}
