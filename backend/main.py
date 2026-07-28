import asyncio
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.insights import router as insights_router
from routers.marine import router as marine_router
from routers.tiles import router as tiles_router
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

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(title="MarisAI Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(marine_router)
app.include_router(insights_router)
app.include_router(tiles_router)


@app.get("/")
def healthcheck():
    return {"status": "ok"}
