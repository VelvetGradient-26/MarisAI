"""Forecast map endpoints — the forecasting engine as a raster layer.

Thin, per the backend convention: catch the service's own error type, map it to
a real status code, never leak a traceback.

The same split failure contract as `routers/predictions.py` and
`routers/tiles.py`: metadata endpoints raise, because a caller building a layer
list needs to know the grid is missing; tile endpoints return a transparent PNG,
because a grid of broken-image icons across the map is worse than an absent
layer.
"""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Response

from services import forecast_tiles
from services.forecast_tiles import MODE_ABSOLUTE, MODES, ForecastTileError

router = APIRouter(prefix="/api/tiles/forecast", tags=["forecast-map"])


@router.get("/catalog")
async def get_catalog():
    """Which variables have a forecast grid, and everything a legend needs.

    Returns 200 with an empty list when nothing has been built yet. An empty
    catalog is a true statement about the system — no grid has been produced —
    not an error, and the map should render without the layers rather than
    fail.
    """
    return {"grids": await asyncio.to_thread(forecast_tiles.catalog)}


@router.get("/point")
async def get_forecast_point(
    variable: str,
    horizon: int = Query(..., ge=1),
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
):
    """The forecast the layer is painting at one coordinate."""
    try:
        return await asyncio.to_thread(
            forecast_tiles.point, variable, horizon, latitude, longitude
        )
    except ForecastTileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{variable}/{horizon}/{mode}/{z}/{x}/{y}.png")
async def get_forecast_tile(
    variable: str, horizon: int, mode: str, z: int, x: int, y: int
):
    if mode not in MODES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown mode {mode!r}; expected one of {', '.join(MODES)}",
        )
    # CPU-bound numpy/Pillow work, so off the event loop — same as SST tiles.
    png_bytes = await asyncio.to_thread(
        forecast_tiles.tile_or_placeholder, variable, horizon, mode, z, x, y
    )
    return Response(
        content=png_bytes,
        media_type="image/png",
        # A grid changes only when the scheduled rebuild rewrites it, which is
        # every few hours — but the URL carries no version, so this is kept
        # well below the rebuild interval rather than cached hard like the
        # offline ML exports.
        headers={"Cache-Control": "public, max-age=900"},
    )


__all__ = ["router", "MODE_ABSOLUTE"]
