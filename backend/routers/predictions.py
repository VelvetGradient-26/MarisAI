"""ML prediction endpoints — habitat suitability and bloom risk.

Thin, per the backend convention: catch the service's own error type, map it
to a real status code, never leak a traceback.

Two different failure contracts on purpose, matching `routers/tiles.py`:
metadata endpoints raise (the caller needs to know the export is missing),
tile endpoints return a transparent PNG (a broken-image grid across the map is
worse than an absent layer).
"""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Response

from services import predictions
from services.predictions import PredictionError

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("/manifest")
async def get_manifest():
    """Available products, their measured skill, drivers and caveats."""
    try:
        return predictions.manifest()
    except PredictionError as exc:
        # 503 rather than 404: the endpoint exists and will work once the
        # offline export has been run, which is an operator action.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/habitat/point")
async def get_habitat_point(
    species: str,
    month: int = Query(..., ge=1, le=12),
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
):
    try:
        return await asyncio.to_thread(
            predictions.habitat_point, species, month, latitude, longitude
        )
    except PredictionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/hab/point")
async def get_hab_point(
    horizon: int,
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    date: str | None = None,
):
    try:
        return await asyncio.to_thread(
            predictions.hab_point, horizon, latitude, longitude, date
        )
    except PredictionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/habitat/{species}/{month}/{z}/{x}/{y}.png")
async def get_habitat_tile(species: str, month: int, z: int, x: int, y: int):
    # CPU-bound numpy/Pillow work, so off the event loop — same as SST tiles.
    png_bytes = await asyncio.to_thread(
        predictions.habitat_tile_or_placeholder, species, month, z, x, y
    )
    return Response(
        content=png_bytes,
        media_type="image/png",
        # Exports change only when the offline pipeline is re-run, so these
        # are safe to cache hard.
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/hab/{horizon}/{z}/{x}/{y}.png")
async def get_hab_tile(horizon: int, z: int, x: int, y: int, date: str | None = None):
    png_bytes = await asyncio.to_thread(
        predictions.hab_tile_or_placeholder, horizon, date, z, x, y
    )
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
