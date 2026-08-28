"""Metric intelligence endpoints — the descriptive half of a variable's page.

Thin, per the backend convention: validate, call one service function, map that
service's error type to a real status code, never leak a traceback.

Status codes follow the same rule `forecasting/api.py` established, and for the
same reason: an **upstream outage is a 503, not a 404**. `ProviderUnavailableError`
subclasses `HistoryError`, so it must be checked first or a transient Copernicus
timeout would be reported as "no data at this point — it may be over land" and
send the reader to check coordinates that were never wrong.
"""

from __future__ import annotations

import logging
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from forecasting import ForecastingError
from forecasting.history import HistoryError, ProviderUnavailableError
from forecasting.registry import UnknownVariableError
from services.metrics import MetricsError
from services.metrics import series as series_service
from services.metrics import statistics as statistics_service
from services.metrics import story as story_service
from services.rate_limit import RateLimiter, enforce

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

# The series and statistics endpoints are cheap once the history cache is warm
# and an upstream fetch when it is not. The story endpoint additionally makes an
# LLM call, so it gets its own tighter budget.
_DATA_LIMITER = RateLimiter(limit=60, window_seconds=60)
_STORY_LIMITER = RateLimiter(limit=12, window_seconds=60)

_LATITUDE = Query(..., ge=-90, le=90)
_LONGITUDE = Query(..., ge=-180, le=180)


def _raise_for(exc: Exception) -> NoReturn:
    """Translate a service error into an HTTP status. Never re-raises raw.

    `NoReturn` rather than `None`: every branch raises, and saying so is what
    lets a caller write `except ...: _raise_for(exc)` as the last statement in
    a function without a type checker demanding an unreachable return.
    """
    if isinstance(exc, ProviderUnavailableError):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{exc} This is an upstream outage and usually clears on its own.",
            headers={"Retry-After": "60"},
        ) from exc
    if isinstance(exc, UnknownVariableError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, HistoryError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, MetricsError):
        # A well-formed request the data cannot satisfy — an empty window, a
        # point over land. 404 rather than 422: the request was valid.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ForecastingError):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    raise HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
    ) from exc


@router.get("/ranges")
async def get_ranges() -> dict[str, Any]:
    """The named history windows the UI may request.

    Served rather than hardcoded in the frontend so the two cannot disagree
    about what "1y" spans — the same reason the trends catalog exists.
    """
    return {
        "ranges": [
            {"key": key, "days": days} for key, days in series_service.RANGES.items()
        ],
        "default": "1y",
        "max_points_limit": series_service.MAX_POINTS_LIMIT,
    }


@router.get("/{variable}/series")
async def get_series(
    request: Request,
    variable: str = Path(..., min_length=1, max_length=64),
    latitude: float = _LATITUDE,
    longitude: float = _LONGITUDE,
    range_key: str | None = Query(None, alias="range"),
    days: int | None = Query(None, ge=1, le=3652),
    max_points: int = Query(
        series_service.DEFAULT_MAX_POINTS, ge=4, le=series_service.MAX_POINTS_LIMIT
    ),
) -> dict[str, Any]:
    """Plottable point history for one variable.

    Decimated to `max_points` using a min/max envelope, so the rendered line
    still touches every peak and trough of the full record — see
    `services/metrics/series.decimate` for why stride sampling is not used.
    """
    enforce(_DATA_LIMITER, request, "Too many history requests. Please wait a moment.")
    try:
        result = await series_service.build(
            variable, latitude, longitude,
            range_key=range_key, days=days, max_points=max_points,
        )
    except Exception as exc:  # noqa: BLE001 - mapped below, never leaked
        _raise_for(exc)
    return result.as_dict()


@router.get("/{variable}/statistics")
async def get_statistics(
    request: Request,
    variable: str = Path(..., min_length=1, max_length=64),
    latitude: float = _LATITUDE,
    longitude: float = _LONGITUDE,
    range_key: str | None = Query(None, alias="range"),
    days: int | None = Query(None, ge=1, le=3652),
) -> dict[str, Any]:
    """The KPI strip.

    Always 200 when the record exists: an individual statistic that cannot be
    computed reports `available: false` with a reason rather than a zero, so a
    365-day change over an 8-month record reads as "needs 365 days" instead of
    claiming the ocean did not change.
    """
    enforce(_DATA_LIMITER, request, "Too many statistics requests. Please wait a moment.")
    try:
        return await statistics_service.build(
            variable, latitude, longitude, range_key=range_key, days=days
        )
    except Exception as exc:  # noqa: BLE001
        _raise_for(exc)


@router.get("/{variable}/story")
async def get_story(
    request: Request,
    variable: str = Path(..., min_length=1, max_length=64),
    latitude: float = _LATITUDE,
    longitude: float = _LONGITUDE,
    range_key: str | None = Query("1y", alias="range"),
    horizon: int | None = Query(7, ge=1, le=365),
) -> dict[str, Any]:
    """The Ocean Story narrative.

    Every figure is computed server-side before the model is called; the model
    only phrases them, and a response containing a number it was not given is
    discarded in favour of the deterministic rendering. The `source` field says
    which path produced the text, so the UI can badge a generated story
    differently from a templated one.
    """
    enforce(
        _STORY_LIMITER,
        request,
        "Too many summary requests. Each one runs a language model; "
        "please wait a moment and retry.",
    )
    try:
        return await story_service.build(
            variable, latitude, longitude, range_key=range_key, horizon=horizon
        )
    except Exception as exc:  # noqa: BLE001
        _raise_for(exc)
