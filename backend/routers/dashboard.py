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

from services.dashboard import alerts, health, live, summary, trends
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


@router.get("/alerts")
async def get_alerts():
    """Threshold-derived alerts, most severe first."""
    return alerts.build()


@router.get("/health")
async def get_health():
    """Per-provider connection, latency and freshness."""
    return health.build()


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
