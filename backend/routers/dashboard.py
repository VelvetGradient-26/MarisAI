"""Ocean intelligence dashboard endpoints.

Thin, per the backend convention: catch each service's own error type, map it
to a real status code, never leak a traceback.

Status codes here follow one rule. A section whose *source has not loaded*
returns 200 with per-item `available: false` rather than an error, because the
dashboard is a grid of independent widgets and one cold cache should not blank
the page — the widget renders its own explanation instead. Only a request that
cannot be satisfied at all (an unknown variable, a range predating a
product's coverage) is a 4xx, and only a wholly unavailable aggregate is 503.
"""

from fastapi import APIRouter, HTTPException, Query

from services import correlation
from services.correlation import CorrelationError
from services.dashboard import alerts, data_quality, health, live, summary, trends
from services.dashboard.trends import TrendsError

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_summary():
    """The six KPI cards. Always 200: unavailable cards say so individually."""
    return summary.build()


@router.get("/live")
async def get_live(
    limit: int = Query(6, ge=1, le=20),
    latitude: float | None = Query(None, ge=-90, le=90),
    longitude: float | None = Query(None, ge=-180, le=180),
):
    """Freshest observations and products.

    With a coordinate the buoy entries become the nearest stations rather than
    the most recently reported ones.
    """
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=422,
            detail="latitude and longitude must be supplied together",
        )
    return live.build(limit=limit, latitude=latitude, longitude=longitude)


@router.get("/stations/{station_id}")
async def get_station_detail(station_id: str):
    """One buoy's full latest observation, plus a short excerpt of its own
    live text feed as provenance — the click-through target from a Live
    Ocean Feed card."""
    from services import ndbc

    try:
        observation = ndbc.station(station_id)
    except ndbc.NdbcError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    raw_feed_data = None
    raw_feed_error = None
    try:
        raw_feed_data = await ndbc.raw_feed(station_id)
    except ndbc.NdbcError as exc:
        raw_feed_error = str(exc)

    return {"station": observation, "raw_feed": raw_feed_data, "raw_feed_error": raw_feed_error}


@router.get("/alerts")
async def get_alerts():
    """Threshold-derived alerts, most severe first."""
    return alerts.build()


@router.get("/health")
async def get_health():
    """Per-provider connection, latency and freshness."""
    return health.build()


@router.get("/sources/{key}")
async def get_source_detail(key: str):
    """One data source's current status, why it reads that way, and a short
    recent-health sparkline — the click-through target from a Data Source
    Status card."""
    try:
        return health.detail(key)
    except health.HealthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/data-quality")
async def get_data_quality():
    """Datasets, model scores and pipeline coverage.

    The standing companion to `/health`: that one answers "is the feed up right
    now", this one answers "what is in the feed and how good is it". Always
    200 — an unreadable model artifact or a missing grid directory is reported
    as an unavailable *item*, since a data-quality panel that goes blank when
    one thing is wrong cannot report that one thing is wrong.
    """
    return data_quality.build()


@router.get("/data-quality/models")
async def get_model_health():
    """Just the model table, for the metric pages' model-health section."""
    return {"models": data_quality.models()}


@router.get("/satellites")
async def get_satellites():
    """Recent satellite products and how far behind real time each is."""
    from services import gibs

    try:
        return {"products": gibs.products(), "meta": gibs.meta()}
    except gibs.GibsError as exc:
        # 503 rather than 404: the endpoint is real and works once the
        # scheduled capabilities fetch has completed.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/trends/catalog")
async def get_trends_catalog():
    """Which variables can be charted and over what ranges.

    Coverage genuinely differs per variable, so the UI reads this rather than
    assuming every range works everywhere.
    """
    return {"variables": trends.catalog(), "ranges": trends.RANGES}


@router.get("/trends")
async def get_trends(
    variable: str = Query(..., description="Variable key from /trends/catalog"),
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    range_key: str = Query("7d", alias="range"),
):
    """One variable's historical series at a point."""
    try:
        return await trends.series(variable, latitude, longitude, range_key)
    except TrendsError as exc:
        # The service raises this for an unknown variable, an unavailable one
        # and an out-of-coverage range alike — all client-correctable.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/trends/multi")
async def get_trends_multi(
    variables: str = Query(..., description="Comma-separated variable keys"),
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    range_key: str = Query("7d", alias="range"),
):
    """Several series in one round trip, for the chart grid.

    Per-series failures are reported inside the payload rather than failing
    the request, so one unavailable variable leaves the rest chartable.
    """
    keys = [key.strip() for key in variables.split(",") if key.strip()]
    if not keys:
        raise HTTPException(status_code=422, detail="No variables requested")
    if len(keys) > 8:
        raise HTTPException(status_code=422, detail="At most 8 variables per request")

    return await trends.multi_series(keys, latitude, longitude, range_key)


@router.get("/trends/correlation")
async def get_trends_correlation(
    variables: str = Query(..., description="2-4 comma-separated variable keys"),
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    range_key: str = Query("1y", alias="range"),
):
    """Pairwise correlation between 2-4 variables at a point, on a shared
    daily-aggregated window. See `services/correlation.py` for why hourly
    ranges are refused and why fishing effort / upwelling are not offered.
    """
    keys = [key.strip() for key in variables.split(",") if key.strip()]
    try:
        return await correlation.analyze(keys, latitude, longitude, range_key)
    except CorrelationError as exc:
        # Malformed request (variable count, hourly-only range) — the same
        # client-correctable class TrendsError already gets 400 for above.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
