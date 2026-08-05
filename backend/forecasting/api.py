"""HTTP surface for the forecasting engine.

Thin, per this backend's router convention: validate, call one service
function, map that service's own error type to a real status code. No
modelling logic lives here, and no raw LightGBM/xarray/copernicusmarine
traceback ever reaches a client.

This router lives inside the `forecasting` package rather than in `routers/`
because the engine is a self-contained subsystem with its own error taxonomy,
and keeping the mapping next to the errors it maps is what stops the two
drifting apart. `main.py` includes it exactly like any other router.

Status codes follow one rule, borrowed from the dashboard: **an untrained
model is a 404 that tells you how to train it, not a 500.** "This variable has
no model yet" is a true, actionable, permanent-until-you-act answer, and
dressing it as a server fault sends people debugging the wrong thing.
"""

from __future__ import annotations

import logging
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from forecasting import ForecastingError
from forecasting.config import get_config
from forecasting.history import HistoryError, ProviderUnavailableError
from forecasting.model_store import ModelNotTrainedError, ModelStoreError
from forecasting.model_store import load as load_artifact
from forecasting.model_store import summary as model_summary
from forecasting.predictor import PredictionError, predict
from forecasting.registry import (
    UnknownVariableError,
    UnsupportedHorizonError,
    catalog,
    grouped_catalog,
    resolve,
    validate_horizon,
)
from services.rate_limit import RateLimiter, enforce

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/forecast", tags=["forecasting"])

# A forecast costs an upstream history fetch (8-13s uncached against
# Copernicus) plus a fit-free inference. The cache absorbs repeats, so this
# limit exists to stop an automated caller walking a grid of coordinates and
# turning the free-tier provider quota into a denial of service against the
# rest of the platform.
_FORECAST_LIMITER = RateLimiter(limit=30, window_seconds=60)
_BATCH_LIMITER = RateLimiter(limit=10, window_seconds=60)


# --------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------


class ForecastRequest(BaseModel):
    """The spec's request shape."""

    variable: str = Field(..., min_length=1, max_length=64)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    forecast_horizon: int = Field(7, ge=1, le=365)
    # Days of context returned alongside the forecast, for the chart. The
    # model's own feature lookback is added on top of this internally, so a
    # small window here never starves the features.
    history_window: int = Field(90, ge=7, le=3650)
    # How many SHAP drivers to return.
    top_features: int = Field(5, ge=1, le=20)
    include_history: bool = True


class BatchForecastRequest(BaseModel):
    """Several horizons at one point — the dashboard's forecast curve."""

    variable: str = Field(..., min_length=1, max_length=64)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    horizons: list[int] = Field(..., min_length=1, max_length=8)
    history_window: int = Field(90, ge=7, le=3650)
    top_features: int = Field(5, ge=1, le=20)


# --------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------


def _raise_for(exc: ForecastingError) -> NoReturn:
    """Translate an engine error into an HTTP status. Never re-raises raw."""
    if isinstance(exc, ModelNotTrainedError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, UnknownVariableError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, UnsupportedHorizonError):
        # Literal 422 rather than the constant: starlette renamed
        # HTTP_422_UNPROCESSABLE_ENTITY to ..._CONTENT and deprecated the old
        # spelling, so naming either one pins this file to a version range.
        raise HTTPException(422, detail=str(exc)) from exc
    if isinstance(exc, ProviderUnavailableError):
        # Checked before HistoryError, which it subclasses. An upstream 5xx or
        # timeout is transient — telling the user their point may be over land
        # would send them to fix coordinates that were never wrong.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{exc} This is an upstream outage and usually clears on its own.",
            headers={"Retry-After": "60"},
        ) from exc
    if isinstance(exc, HistoryError):
        # The request was well-formed; the upstream data does not exist for
        # that point/window. 404 rather than 502 because retrying will not
        # help — the point is over land, or before coverage.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ModelStoreError):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    if isinstance(exc, PredictionError):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    raise HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
    ) from exc


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@router.post("")
async def create_forecast(payload: ForecastRequest, request: Request) -> dict[str, Any]:
    """Forecast one variable at one point.

    Returns the prediction, a bootstrap confidence interval, the trend against
    the latest observation, the SHAP drivers behind this specific number, the
    model's out-of-sample evaluation, and the provenance of every input.
    """
    enforce(
        _FORECAST_LIMITER,
        request,
        "Too many forecast requests. Each one fetches live ocean data; "
        "please wait a moment and retry.",
    )

    try:
        forecast = await predict(
            payload.variable,
            payload.latitude,
            payload.longitude,
            payload.forecast_horizon,
            history_window=payload.history_window,
            top_k=payload.top_features,
            include_history=payload.include_history,
        )
    except ForecastingError as exc:
        _raise_for(exc)
    except Exception as exc:  # noqa: BLE001 - no traceback may reach a client
        logger.exception("unexpected error producing a forecast")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The forecast could not be produced due to an internal error.",
        ) from exc

    return forecast.as_dict()


@router.post("/batch")
async def create_batch_forecast(
    payload: BatchForecastRequest, request: Request
) -> dict[str, Any]:
    """Several horizons at one point, for a forecast curve with a widening band.

    A horizon that has no trained model takes its own slot down with an error
    string and leaves the rest intact — the same contract the dashboard's
    multi-series endpoint uses, so one untrained horizon does not blank a
    chart that four others could fill.
    """
    enforce(
        _BATCH_LIMITER,
        request,
        "Too many batch forecast requests. Please wait a moment and retry.",
    )

    results: dict[str, Any] = {}
    for index, horizon in enumerate(sorted(set(payload.horizons))):
        try:
            forecast = await predict(
                payload.variable,
                payload.latitude,
                payload.longitude,
                horizon,
                history_window=payload.history_window,
                top_k=payload.top_features,
                # The history is identical across horizons, so it rides along
                # with the first and is omitted from the rest — a five-horizon
                # response otherwise carries five copies of the same series.
                # It must be sent *once*, though: omitting it everywhere leaves
                # the forecast chart with nothing to anchor the predicted path
                # against, which is most of what makes the chart readable.
                include_history=index == 0,
            )
            results[str(horizon)] = forecast.as_dict()
        except ForecastingError as exc:
            results[str(horizon)] = {"horizon": horizon, "error": str(exc)}

    if all("error" in entry for entry in results.values()):
        # Every horizon failed for the same underlying reason; surface it as
        # an error rather than a 200 full of failures.
        first = next(iter(results.values()))["error"]
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=first)

    return {
        "variable": payload.variable,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "forecasts": results,
    }


@router.get("/catalog")
async def get_catalog(grouped: bool = Query(False)) -> dict[str, Any]:
    """What can be forecast, over which horizons, and what is trained.

    Always 200. A configured-but-untrained variable is listed with
    `available: false` and a reason, exactly as the dashboard's other
    catalogs do — the UI can then grey it out instead of offering a forecast
    that 404s.
    """
    config = get_config()
    entries = (
        grouped_catalog(config) if grouped else [entry.as_dict() for entry in catalog(config)]
    )
    return {
        "variables": entries,
        "supported_horizons": config.defaults.supported_horizons,
        "default_horizons": config.defaults.horizons,
        "model": "LightGBM",
        "validation": "rolling-origin cross-validation",
    }


@router.get("/models")
async def get_models() -> dict[str, Any]:
    """The model registry: every trained artifact with its headline metrics."""
    return {"models": model_summary()}


@router.get("/models/{variable}/{horizon}")
async def get_model_detail(variable: str, horizon: int) -> dict[str, Any]:
    """Full metadata, metrics and diagnostics for one trained model.

    This is what backs the explainability and evaluation panels: the SHAP
    global importance ranking, the per-fold validation scores, and the
    prediction-vs-actual / residual / error-distribution arrays, as data for
    the frontend to plot in its own theme.
    """
    try:
        validate_horizon(horizon)
        artifact = load_artifact(variable, horizon)
    except ForecastingError as exc:
        _raise_for(exc)

    return {
        "variable": variable,
        "horizon": horizon,
        "metadata": artifact.metadata,
        "metrics": artifact.metrics,
        "feature_columns": artifact.feature_columns,
    }


@router.get("/variables/{variable}")
async def get_variable_detail(variable: str) -> dict[str, Any]:
    """One variable's forecasting configuration, for the intelligence page header."""
    try:
        config = get_config()
        entry = resolve(variable, config)
    except ForecastingError as exc:
        _raise_for(exc)

    return {
        "key": variable,
        "label": entry.label,
        "unit": entry.unit,
        "category": entry.category,
        "covariates": entry.covariates,
        "circular": entry.circular,
        "log_transform": entry.log_transform,
        "valid_min": entry.valid_min,
        "valid_max": entry.valid_max,
        "horizons": config.horizons_for(variable),
    }
